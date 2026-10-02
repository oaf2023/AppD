"""store — consultas y agregación tick→vela del pipeline propio (K §4.4, BUILD-027/030).

Agregación multi-timeframe en proceso (`1m`, `5m`, `15m`, `1h`, `4h`, `1d` —
BUILD-030): open/close = primer/último tick del bucket por `(ts, id)`;
high/low = extremos del precio; `volume` = suma de tamaños **solo si todos los
ticks del bucket lo informan**, si no `NULL` (jamás se fabrica dato). La vela
existente se recalcula desde los ticks (`gap=false`); los buckets cerrados sin
ticks se insertan como hueco (`gap=true`, OHLC/volumen `NULL` — K §4.4(c)).
Cada timeframe es una función pura de los ticks ⇒ replay idéntico
(`tests/integration/test_market_data_candles_multi_tf.py`, BUILD-030).

Buckets alineados a UTC: `5m`/`15m` al múltiplo, `1h` a la hora, `4h` a
00/04/08/12/16/20 y `1d` a medianoche UTC (día calendario, sin sesión).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from market_data.domain.models import Candle, Tick, Timeframe
from market_data.pagination import encode_cursor
from market_data.tables import CandleRow, TickRow

TIMEDELTA_1M = timedelta(minutes=1)

#: Duración de cada bucket; la alineación es a UTC (ver `bucket_start`).
TIMEFRAME_DELTAS: dict[Timeframe, timedelta] = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def bucket_start(ts: datetime, timeframe: Timeframe) -> datetime:
    """Inicio UTC del bucket de `ts` para `timeframe` (BUILD-030).

    Reglas: `1m`→minuto; `5m`/`15m`→múltiplo; `1h`→hora; `4h`→00/04/08/12/16/20;
    `1d`→medianoche UTC (día calendario, sin sesión). Con `ts` naive se comporta
    igual: las capas superiores exigen zona horaria.
    """
    if timeframe == "1m":
        return ts.replace(second=0, microsecond=0)
    if timeframe == "5m":
        return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)
    if timeframe == "15m":
        return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
    if timeframe == "1h":
        return ts.replace(minute=0, second=0, microsecond=0)
    if timeframe == "4h":
        return ts.replace(hour=(ts.hour // 4) * 4, minute=0, second=0, microsecond=0)
    return ts.replace(hour=0, minute=0, second=0, microsecond=0)  # 1d


def bucket_start_1m(ts: datetime) -> datetime:
    return bucket_start(ts, "1m")


@dataclass(frozen=True, slots=True)
class FeedCounts:
    ticks: int
    candles: int
    gaps: int
    last_tick_ts: datetime | None
    last_latency_ms: int | None


async def max_tick_ts(session: AsyncSession, symbol: str) -> datetime | None:
    stmt = select(func.max(TickRow.ts)).where(TickRow.symbol == symbol)
    return (await session.execute(stmt)).scalar_one_or_none()


async def latest_tick_row(session: AsyncSession, symbol: str) -> TickRow | None:
    stmt = select(TickRow).where(TickRow.symbol == symbol).order_by(TickRow.ts.desc(), TickRow.id.desc()).limit(1)
    return (await session.execute(stmt)).scalars().first()


async def insert_ticks(session: AsyncSession, ticks: Sequence[Tick]) -> list[datetime]:
    """Inserta ticks deduplicados y devuelve los `ts` realmente nuevos."""
    if not ticks:
        return []
    rows = [
        {
            "symbol": tick.symbol,
            "price": tick.price,
            "side": tick.side,
            "size": tick.size,
            "ts": tick.ts,
            "recv_ts": tick.recv_ts,
            "source": tick.source,
            "simulated": tick.simulated,
            "provider_seq": tick.provider_seq,
        }
        for tick in ticks
    ]
    stmt = pg_insert(TickRow).values(rows).on_conflict_do_nothing().returning(TickRow.ts)
    return list((await session.execute(stmt)).scalars())


async def _ticks_in_window(session: AsyncSession, symbol: str, start: datetime, end: datetime) -> list[TickRow]:
    stmt = (
        select(TickRow)
        .where(TickRow.symbol == symbol, TickRow.ts >= start, TickRow.ts < end)
        .order_by(TickRow.ts.asc(), TickRow.id.asc())
    )
    return list((await session.execute(stmt)).scalars())


async def recompute_candles(
    session: AsyncSession,
    symbol: str,
    timeframe: Timeframe,
    buckets: Sequence[datetime],
) -> list[datetime]:
    """Recalcula las velas de `timeframe` en `buckets` desde los ticks (upsert `gap=false`).

    Función pura del conjunto de ticks ⇒ replay idéntico (BUILD-030).
    Devuelve los buckets que efectivamente tienen ticks (=> vela real).
    """
    if not buckets:
        return []
    delta = TIMEFRAME_DELTAS[timeframe]
    start, end = min(buckets), max(buckets) + delta
    ticks = await _ticks_in_window(session, symbol, start, end)
    by_bucket: dict[datetime, list[TickRow]] = {}
    for row in ticks:
        by_bucket.setdefault(bucket_start(row.ts, timeframe), []).append(row)
    real: list[datetime] = []
    for bucket in sorted(set(buckets) & set(by_bucket)):
        group = by_bucket[bucket]
        prices = [row.price for row in group]
        known_sizes = [size for size in (row.size for row in group) if size is not None]
        volume = sum(known_sizes, start=Decimal(0)) if len(known_sizes) == len(group) else None
        stmt = (
            pg_insert(CandleRow)
            .values(
                symbol=symbol,
                timeframe=timeframe,
                bucket_start=bucket,
                open=group[0].price,
                high=max(prices),
                low=min(prices),
                close=group[-1].price,
                volume=volume,
                gap=False,
                source=group[-1].source,
                simulated=all(row.simulated for row in group),
            )
            .on_conflict_do_update(
                index_elements=[CandleRow.symbol, CandleRow.timeframe, CandleRow.bucket_start],
                set_={
                    "open": group[0].price,
                    "high": max(prices),
                    "low": min(prices),
                    "close": group[-1].price,
                    "volume": volume,
                    "gap": False,
                    "source": group[-1].source,
                    "simulated": all(row.simulated for row in group),
                    "updated_at": func.now(),
                },
            )
        )
        await session.execute(stmt)
        real.append(bucket)
    return real


async def recompute_candles_1m(session: AsyncSession, symbol: str, buckets: Sequence[datetime]) -> list[datetime]:
    """Compat: `recompute_candles(..., "1m", ...)`."""
    return await recompute_candles(session, symbol, "1m", buckets)


async def mark_gap_candles(
    session: AsyncSession,
    symbol: str,
    buckets: Sequence[datetime],
    *,
    source: str,
    simulated: bool,
    timeframe: Timeframe = "1m",
) -> int:
    """Inserta `gap=true` en buckets cerrados sin ticks; nunca sobreescribe velas reales."""
    if not buckets:
        return 0
    delta = TIMEFRAME_DELTAS[timeframe]
    start, end = min(buckets), max(buckets) + delta
    with_ticks = {bucket_start(row.ts, timeframe) for row in await _ticks_in_window(session, symbol, start, end)}
    candidates = [bucket for bucket in sorted(set(buckets)) if bucket not in with_ticks]
    if not candidates:
        return 0
    stmt = (
        pg_insert(CandleRow)
        .values(
            [
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "bucket_start": bucket,
                    "open": None,
                    "high": None,
                    "low": None,
                    "close": None,
                    "volume": None,
                    "gap": True,
                    "source": source,
                    "simulated": simulated,
                }
                for bucket in candidates
            ]
        )
        .on_conflict_do_nothing()
        .returning(CandleRow.id)
    )
    # psycopg3 en modo batch expone `rowcount=-1`; las filas devueltas son la
    # fuente fiable de "realmente insertadas" (los conflictos no devuelven nada).
    return len(list((await session.execute(stmt)).scalars()))


def gap_candidates_between(
    lower_bucket: datetime,
    max_bucket: datetime,
    timeframe: Timeframe = "1m",
) -> list[datetime]:
    """Buckets estrictamente entre `lower_bucket` y `max_bucket` (cierre de huecos).

    `lower_bucket` es el bucket del último tick previo a la pasada o, si no lo
    hay, el bucket inferior de la propia pasada: la ventana de observación
    empieza en el primer tick y jamás se fabrican velas para el pasado.
    Los buckets con ticks reales se filtran después en `mark_gap_candles`.
    """
    delta = TIMEFRAME_DELTAS[timeframe]
    candidates: list[datetime] = []
    cursor = lower_bucket + delta
    while cursor < max_bucket:
        candidates.append(cursor)
        cursor += delta
    return candidates


async def list_tick_rows(
    session: AsyncSession,
    *,
    symbol: str,
    from_ts: datetime,
    to_ts: datetime,
    cursor: tuple[datetime, UUID] | None,
    limit: int,
) -> tuple[list[TickRow], bool]:
    conditions = [
        TickRow.symbol == symbol,
        TickRow.ts >= from_ts,
        TickRow.ts <= to_ts,
    ]
    if cursor is not None:
        cursor_ts, cursor_id = cursor
        conditions.append(
            or_(
                TickRow.ts < cursor_ts,
                and_(TickRow.ts == cursor_ts, TickRow.id < cursor_id),
            )
        )
    stmt = select(TickRow).where(*conditions).order_by(TickRow.ts.desc(), TickRow.id.desc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars())
    has_more = len(rows) > limit
    return rows[:limit], has_more


async def list_candle_rows(
    session: AsyncSession,
    *,
    symbol: str,
    timeframe: Timeframe,
    from_ts: datetime | None,
    to_ts: datetime | None,
    cursor: tuple[datetime, UUID] | None,
    limit: int,
) -> tuple[list[CandleRow], bool]:
    conditions = [CandleRow.symbol == symbol, CandleRow.timeframe == timeframe]
    if from_ts is not None:
        conditions.append(CandleRow.bucket_start >= from_ts)
    if to_ts is not None:
        conditions.append(CandleRow.bucket_start <= to_ts)
    if cursor is not None:
        cursor_ts, cursor_id = cursor
        conditions.append(
            or_(
                CandleRow.bucket_start < cursor_ts,
                and_(CandleRow.bucket_start == cursor_ts, CandleRow.id < cursor_id),
            )
        )
    stmt = (
        select(CandleRow)
        .where(*conditions)
        .order_by(CandleRow.bucket_start.desc(), CandleRow.id.desc())
        .limit(limit + 1)
    )
    rows = list((await session.execute(stmt)).scalars())
    has_more = len(rows) > limit
    return rows[:limit], has_more


async def feed_counts(session: AsyncSession) -> FeedCounts:
    ticks = int((await session.execute(select(func.count(TickRow.id)))).scalar_one())
    candles = int((await session.execute(select(func.count(CandleRow.id)))).scalar_one())
    gaps = int((await session.execute(select(func.count(CandleRow.id)).where(CandleRow.gap.is_(True)))).scalar_one())
    newest = (
        await session.execute(
            select(TickRow.ts, TickRow.recv_ts).order_by(TickRow.ts.desc(), TickRow.id.desc()).limit(1)
        )
    ).first()
    if newest is None:
        return FeedCounts(ticks=ticks, candles=candles, gaps=gaps, last_tick_ts=None, last_latency_ms=None)
    last_ts, recv_ts = newest
    # Aritmética entera de timedelta (sin float, ADR-0006): recv_ts < ts ⇒ skew ⇒ 0.
    latency_ms = max(0, int((recv_ts - last_ts) / timedelta(milliseconds=1)))
    return FeedCounts(ticks=ticks, candles=candles, gaps=gaps, last_tick_ts=last_ts, last_latency_ms=latency_ms)


def tick_cursor(row: TickRow) -> str:
    return encode_cursor(row.ts, row.id)


def candle_cursor(row: CandleRow) -> str:
    return encode_cursor(row.bucket_start, row.id)


async def candle_rows_for(
    session: AsyncSession,
    symbol: str,
    buckets: Sequence[datetime],
    *,
    timeframe: Timeframe = "1m",
) -> list[CandleRow]:
    """Velas de `timeframe` en `buckets` para el fan-out WS (post-commit)."""
    if not buckets:
        return []
    stmt = (
        select(CandleRow)
        .where(
            CandleRow.symbol == symbol,
            CandleRow.timeframe == timeframe,
            CandleRow.bucket_start.in_(buckets),
        )
        .order_by(CandleRow.bucket_start.asc())
    )
    return list((await session.execute(stmt)).scalars())


def row_to_tick(row: TickRow) -> Tick:
    return Tick(
        symbol=row.symbol,
        price=row.price,
        side=row.side,  # type: ignore[arg-type]  # validado por chk_tick_side
        size=row.size,
        ts=row.ts,
        recv_ts=row.recv_ts,
        source=row.source,
        simulated=row.simulated,
        provider_seq=row.provider_seq,
    )


def row_to_candle(row: CandleRow) -> Candle:
    return Candle(
        symbol=row.symbol,
        timeframe=row.timeframe,  # type: ignore[arg-type]  # validado por chk_candle_timeframe
        ts=row.bucket_start,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        gap=row.gap,
        source=row.source,
        simulated=row.simulated,
    )


__all__ = [
    "TIMEDELTA_1M",
    "TIMEFRAME_DELTAS",
    "FeedCounts",
    "bucket_start",
    "bucket_start_1m",
    "candle_cursor",
    "candle_rows_for",
    "feed_counts",
    "gap_candidates_between",
    "insert_ticks",
    "latest_tick_row",
    "list_candle_rows",
    "list_tick_rows",
    "mark_gap_candles",
    "max_tick_ts",
    "recompute_candles",
    "recompute_candles_1m",
    "row_to_candle",
    "row_to_tick",
    "tick_cursor",
]
