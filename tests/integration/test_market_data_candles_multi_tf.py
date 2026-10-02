"""Casos dorados del agregador tick→vela multi-timeframe (BUILD-030, K §4.4).

Fechas fijas y en el pasado (la normalización sólo rechaza ticks futuros):
cada timeframe se compara contra OHLC esperado a mano y el replay con el mismo
conjunto de ticks en otro orden debe producir velas byte a byte idénticas
(función pura, sin reloj real).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from market_data.db import get_session_factory
from market_data.domain.models import TIMEFRAMES, Timeframe
from market_data.ingest import IngestService
from market_data.normalization import RawTick
from market_data.store import bucket_start, list_candle_rows
from market_data.tables import CandleRow, TickRow
from sqlalchemy import delete

pytestmark = pytest.mark.integration

SYMBOL = "EUR/USD"

# Lunes 2026-03-02 (fijo): 10:00Z alinea 15m/1h y cae en el bucket 4h 08:00Z
T1 = datetime(2026, 3, 2, 10, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 3, 2, 10, 2, 30, tzinfo=UTC)
T3 = datetime(2026, 3, 2, 10, 4, 59, tzinfo=UTC)
T4 = datetime(2026, 3, 2, 10, 7, 0, tzinfo=UTC)
T5 = datetime(2026, 3, 2, 10, 19, 59, tzinfo=UTC)

DAY = datetime(2026, 3, 2, 0, 0, 0, tzinfo=UTC)
# o/h/l/c de los 15 ticks combinados (1.1000 abre, 1.0990 cierra tras tocar 1.1100)
ALL_OHLC = ("1.1000", "1.1100", "1.0990", "1.0990")

Row = tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None, Decimal | None, bool]


@pytest.fixture(autouse=True)
async def _wipe(market_data_app):  # type: ignore[no-untyped-def]
    """Vacia `market_data` antes de cada test: los tests no comparten estado."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(TickRow))
        await session.execute(delete(CandleRow))
        await session.commit()


def _raw(ts: datetime, price: str, *, size: str | None = None) -> RawTick:
    return RawTick(
        symbol=SYMBOL,
        price=price,
        side="na",
        size=size,
        ts=ts,
        source="MOCK",
        simulated=True,
        recv_ts=ts,
    )


def _service() -> IngestService:
    from market_data.config import get_market_data_settings
    from market_data.providers.factory import create_market_data_provider

    return IngestService(get_session_factory(), create_market_data_provider(get_market_data_settings()))


async def _ingest(raws: list[RawTick], now: datetime):  # type: ignore[no-untyped-def]
    return await _service().ingest_raw(raws, now=now)


async def _snapshot() -> dict[tuple[Timeframe, datetime], Row]:
    """Todas las velas de todos los timeframes como dict determinista."""
    factory = get_session_factory()
    out: dict[tuple[Timeframe, datetime], Row] = {}
    async with factory() as session:
        for timeframe in TIMEFRAMES:
            rows, _ = await list_candle_rows(
                session,
                symbol=SYMBOL,
                timeframe=timeframe,
                from_ts=DAY,
                to_ts=DAY + timedelta(days=1),
                cursor=None,
                limit=200,
            )
            for row in rows:
                out[(timeframe, row.bucket_start)] = (
                    row.open,
                    row.high,
                    row.low,
                    row.close,
                    row.volume,
                    row.gap,
                )
    return out


def _real(o: str, h: str, lo: str, c: str, v: str | None) -> Row:
    return (Decimal(o), Decimal(h), Decimal(lo), Decimal(c), Decimal(v) if v else None, False)


def _gap() -> Row:
    return (None, None, None, None, None, True)


GOLDEN = [
    _raw(T1, "1.1000", size="10"),
    _raw(T2, "1.1050"),  # sin tamaño ⇒ volume NULL en su bucket
    _raw(T3, "1.1020", size="5"),
    _raw(T4, "1.1100", size="2"),
    _raw(T5, "1.0990", size="3"),
]


async def test_ohlc_dorado_en_los_seis_timeframes(market_data_app) -> None:  # type: ignore[no-untyped-def]
    await _ingest(list(GOLDEN), now=T5 + timedelta(seconds=5))
    got = await _snapshot()

    # claves SIEMPRE en bucket (:00), no en el timestamp del tick
    expected: dict[tuple[Timeframe, datetime], Row] = {
        # 1m — buckets con ticks y huecos entre 10:00 y 10:19 (sin fabricar pasado)
        ("1m", T1): _real("1.1000", "1.1000", "1.1000", "1.1000", "10"),
        ("1m", datetime(2026, 3, 2, 10, 2, tzinfo=UTC)): _real(
            "1.1050", "1.1050", "1.1050", "1.1050", None
        ),  # T2 sin tamaño ⇒ vol NULL
        ("1m", datetime(2026, 3, 2, 10, 4, tzinfo=UTC)): _real("1.1020", "1.1020", "1.1020", "1.1020", "5"),
        ("1m", T4): _real("1.1100", "1.1100", "1.1100", "1.1100", "2"),
        ("1m", datetime(2026, 3, 2, 10, 19, tzinfo=UTC)): _real("1.0990", "1.0990", "1.0990", "1.0990", "3"),
        # 5m — agregación de tres ticks + hueco parcial 10:10Z
        ("5m", T1): _real("1.1000", "1.1050", "1.1000", "1.1020", None),
        ("5m", datetime(2026, 3, 2, 10, 5, tzinfo=UTC)): _real("1.1100", "1.1100", "1.1100", "1.1100", "2"),
        ("5m", datetime(2026, 3, 2, 10, 15, tzinfo=UTC)): _real("1.0990", "1.0990", "1.0990", "1.0990", "3"),
        ("5m", datetime(2026, 3, 2, 10, 10, tzinfo=UTC)): _gap(),
        # 15m — 10:00Z (cuatro ticks) y 10:15Z; huecos adyacentes no existen
        ("15m", T1): _real("1.1000", "1.1100", "1.1000", "1.1100", None),
        ("15m", datetime(2026, 3, 2, 10, 15, tzinfo=UTC)): _real("1.0990", "1.0990", "1.0990", "1.0990", "3"),
        # 1h/4h/1d — todos los ticks en un único bucket
        ("1h", T1): _real(*ALL_OHLC, None),  # type: ignore[arg-type]
        ("4h", datetime(2026, 3, 2, 8, 0, tzinfo=UTC)): _real(*ALL_OHLC, None),  # type: ignore[arg-type]
        ("1d", DAY): _real(*ALL_OHLC, None),  # type: ignore[arg-type]
    }
    # huecos 1m: 10:01..10:18 salvo los buckets con tick real (10:02, 10:04, 10:07)
    minute = timedelta(minutes=1)
    real_1m = (
        T1,
        datetime(2026, 3, 2, 10, 2, tzinfo=UTC),
        datetime(2026, 3, 2, 10, 4, tzinfo=UTC),
        T4,
        datetime(2026, 3, 2, 10, 19, tzinfo=UTC),
    )
    for i in range(1, 19):
        bucket = T1 + minute * i
        if bucket not in real_1m:
            expected[("1m", bucket)] = _gap()

    assert got == expected
    assert len(got) == 29  # 13 reales (5x1m+3x5m+2x15m+1x1h+1x4h+1x1d) + 15 huecos 1m + 1 hueco 5m


async def test_replay_identico_con_orden_de_ticks_distinto(market_data_app) -> None:  # type: ignore[no-untyped-def]
    await _ingest(list(GOLDEN), now=T5 + timedelta(seconds=5))
    first = await _snapshot()

    factory = get_session_factory()
    async with factory() as session:  # wipe intermedio: mismo estado inicial
        await session.execute(delete(TickRow))
        await session.execute(delete(CandleRow))
        await session.commit()

    shuffled = [GOLDEN[3], GOLDEN[0], GOLDEN[4], GOLDEN[2], GOLDEN[1]]
    stats = await _ingest(shuffled, now=T5 + timedelta(seconds=5))
    assert stats.inserted == 5

    second = await _snapshot()
    assert second == first


async def test_huecos_5m_entre_pasadas_y_reparacion_con_tick_tardio(market_data_app) -> None:  # type: ignore[no-untyped-def]
    bucket5 = lambda ts: bucket_start(ts, "5m")  # noqa: E731

    # pasada 1: sólo 10:00..10:04 ⇒ buckets 5m/15m/1h/… contiguos; sólo huecos 1m
    stats1 = await _ingest(GOLDEN[:3], now=T3 + timedelta(seconds=1))
    assert stats1.gaps_marked == 2  # 10:01 y 10:03 (ticks no contiguos)

    # pasada 2: salto a 10:19 ⇒ 10:05 y 10:10 observados sin ticks
    stats2 = await _ingest([GOLDEN[4]], now=T5 + timedelta(seconds=1))
    assert stats2.gaps_marked == 16  # 2 de 5m + 14 de 1m; 15m/1h/4h/1d sin huecos

    snapshot = await _snapshot()
    five = {bucket: row for (tf, bucket), row in snapshot.items() if tf == "5m"}
    assert set(five) == {
        bucket5(T1),
        datetime(2026, 3, 2, 10, 5, tzinfo=UTC),
        datetime(2026, 3, 2, 10, 10, tzinfo=UTC),
        bucket5(T5),
    }
    assert five[datetime(2026, 3, 2, 10, 5, tzinfo=UTC)] == _gap()
    assert five[datetime(2026, 3, 2, 10, 10, tzinfo=UTC)] == _gap()

    # pasada 3: tick tardío en 10:07 repara el hueco 5m de 10:05 (recompute)
    stats3 = await _ingest([GOLDEN[3]], now=T4 + timedelta(days=1))
    assert stats3.inserted == 1
    snapshot3 = await _snapshot()
    five3 = {bucket: row for (tf, bucket), row in snapshot3.items() if tf == "5m"}
    assert five3[datetime(2026, 3, 2, 10, 5, tzinfo=UTC)] == _real("1.1100", "1.1100", "1.1100", "1.1100", "2")
    assert five3[datetime(2026, 3, 2, 10, 10, tzinfo=UTC)] == _gap()  # sigue vacío
