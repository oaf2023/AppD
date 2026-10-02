"""ingest — normalización, persistencia y agregación de ticks (K §4.4, BUILD-027).

Flujo por pasada (`ingest_once`):

1. el driver canónico (`MarketDataProvider.get_tickers`) entrega los `Ticker`;
2. cada `Quote` se deriva a `RawTick` y se normaliza (`normalization.py`);
   los inválidos van a cuarentena: se cuentan como descartados y **jamás** se
   corrigen ni persisten;
3. se insertan deduplicados (`uq_tick_dedup`: symbol/source/ts/price);
4. se recalcula la vela 1m de los buckets tocados (open/close primer/último,
   high/low extremos, invariante REQ-028 estructural);
5. los buckets cerrados sin ticks entre el tick previo y el nuevo se marcan
   `gap=true` (K §4.4(c), nunca fabricados);
6. **tras el commit**, el hub WebSocket recibe los ticks insertados y las velas
   1m reales (`tick`/`candle` por topic, BUILD-029); los buckets `gap` no se
   publican (REST backfill) y el cache de snapshot queda en el bucket más
   reciente.

`IngestPoller` repite el ciclo cada `ingest_interval_seconds` **solo si**
`ingest_enabled` (apagado por defecto; el deploy lo activa). El fan-out es
in-process: no hay productor de ticks en Redpanda aún (desviación documentada
en K §4; el relay del outbox `SymbolUpdated` sí llega en BUILD-029).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from platform_kernel.clock import utcnow
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from market_data.config import MarketDataSettings
from market_data.domain.models import CanonicalDataError, Quote, Tick
from market_data.domain.protocols import MarketDataProvider, ProviderError
from market_data.format import fmt_price
from market_data.normalization import RawTick, normalize_tick
from market_data.store import (
    bucket_start_1m,
    candle_rows_for,
    gap_candidates_between,
    insert_ticks,
    mark_gap_candles,
    max_tick_ts,
    recompute_candles_1m,
    row_to_candle,
)

if TYPE_CHECKING:
    from market_data.ws import MarketHub

logger = logging.getLogger("market_data.ingest")


@dataclass
class IngestStats:
    """Resultado de una pasada de ingest (para logs, métricas y `GET /status`)."""

    received: int = 0
    inserted: int = 0
    duplicates: int = 0
    quarantined: int = 0
    candles_updated: int = 0
    gaps_marked: int = 0
    symbols: set[str] = field(default_factory=set)


def raw_tick_from_quote(quote: Quote, *, recv_ts: datetime) -> RawTick:
    """Deriva un `RawTick` de una `Quote` canónica (sin lado ni tamaño: `na`/None)."""
    return RawTick(
        symbol=quote.symbol,
        price=quote.last,
        side="na",
        size=None,
        ts=quote.ts,
        source=quote.source,
        simulated=quote.simulated,
        provider_seq=None,
        recv_ts=recv_ts,
    )


class IngestService:
    """Persiste ticks normalizados y sus velas 1m con huecos explícitos."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: MarketDataProvider,
        *,
        clock: Callable[[], datetime] = utcnow,
        hub: MarketHub | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._clock = clock
        self._hub = hub

    async def ingest_once(self) -> IngestStats:
        """Una pasada completa desde el driver canónico."""
        now = self._clock()
        try:
            tickers = await self._provider.get_tickers(None)
        except ProviderError:
            logger.exception("driver canónico no entregó tickers en esta pasada")
            return IngestStats()
        raws = [raw_tick_from_quote(ticker.quote, recv_ts=now) for ticker in tickers]
        return await self.ingest_raw(raws, now=now)

    async def ingest_raw(self, raws: Sequence[RawTick], *, now: datetime) -> IngestStats:
        """Normaliza y persiste ticks crudos; base de los tests de invariantes."""
        stats = IngestStats(received=len(raws))
        ticks: list[Tick] = []
        for raw in raws:
            try:
                ticks.append(normalize_tick(raw, now=now))
            except CanonicalDataError as exc:
                stats.quarantined += 1
                logger.warning("tick en cuarentena: %s", exc)
        if not ticks:
            return stats

        by_symbol: dict[str, list[Tick]] = {}
        for tick in ticks:
            by_symbol.setdefault(tick.symbol, []).append(tick)

        async with self._session_factory() as session:
            inserted_by_symbol: dict[str, list[datetime]] = {}
            real_by_symbol: dict[str, list[datetime]] = {}
            for symbol, symbol_ticks in by_symbol.items():
                prior_ts = await max_tick_ts(session, symbol)
                inserted_ts = await insert_ticks(session, symbol_ticks)
                stats.inserted += len(inserted_ts)
                stats.duplicates += len(symbol_ticks) - len(inserted_ts)
                if not inserted_ts:
                    continue
                stats.symbols.add(symbol)
                inserted_by_symbol[symbol] = inserted_ts
                buckets = sorted({bucket_start_1m(ts) for ts in inserted_ts})
                real_by_symbol[symbol] = await recompute_candles_1m(session, symbol, buckets)
                stats.candles_updated += len(buckets)
                # Huecos: entre el bucket inferior observado (previo o de esta
                # pasada) y el bucket superior, sin fabricar pasado previo al
                # primer tick (K §4.4(c)).
                lower = bucket_start_1m(prior_ts) if prior_ts is not None else min(buckets)
                candidates = gap_candidates_between(lower, max(buckets))
                newest = symbol_ticks[-1]
                stats.gaps_marked += await mark_gap_candles(
                    session, symbol, candidates, source=newest.source, simulated=newest.simulated
                )
            await session.commit()
            # Fan-out WS solo con datos ya duraderos (BUILD-029): velas 1m
            # reales (los huecos van por backfill REST) y ticks insertados.
            if self._hub is not None and inserted_by_symbol:
                await self._publish(session, by_symbol, inserted_by_symbol, real_by_symbol)
        return stats

    async def _publish(
        self,
        session: AsyncSession,
        by_symbol: dict[str, list[Tick]],
        inserted_by_symbol: dict[str, list[datetime]],
        real_by_symbol: dict[str, list[datetime]],
    ) -> None:
        """Publica ticks/velas en el hub in-process (post-commit, BUILD-029)."""
        hub = self._hub
        if hub is None:  # pragma: no cover — defensa; `_publish` solo se llama con hub
            return
        for symbol, inserted_ts in inserted_by_symbol.items():
            # la dedup de BD es (symbol, source, ts, price): un tick repetido
            # en el mismo lote se publica una sola vez
            seen: set[tuple[datetime, object, str]] = set()
            fresh: list[Tick] = []
            for tick in by_symbol[symbol]:
                if tick.ts not in inserted_ts:
                    continue
                key = (tick.ts, tick.price, tick.source)
                if key in seen:
                    continue
                seen.add(key)
                fresh.append(tick)
            topic = f"ticks:{symbol}"
            for tick in sorted(fresh, key=lambda item: item.ts):
                hub.publish(
                    topic,
                    "tick",
                    {
                        "symbol": tick.symbol,
                        "price": fmt_price(tick.price),
                        "side": tick.side,
                        "size": fmt_price(tick.size),
                        "ts": tick.ts.isoformat(),
                        "source": tick.source,
                        "simulated": tick.simulated,
                    },
                )
        for symbol, buckets in real_by_symbol.items():
            if not buckets:
                continue
            topic = f"candles:{symbol}:1m"
            for row in await candle_rows_for(session, symbol, buckets):
                candle = row_to_candle(row)
                hub.publish(
                    topic,
                    "candle",
                    {
                        "symbol": candle.symbol,
                        "timeframe": candle.timeframe,
                        "ts": candle.ts.isoformat(),
                        "open": fmt_price(candle.open),
                        "high": fmt_price(candle.high),
                        "low": fmt_price(candle.low),
                        "close": fmt_price(candle.close),
                        "volume": fmt_price(candle.volume),
                        "gap": candle.gap,
                        "source": candle.source,
                        "simulated": candle.simulated,
                    },
                )


class IngestPoller:
    """Ciclo de vida del loop de ingest (patrón `RetentionSweep`, BUILD-025)."""

    def __init__(self, service: IngestService, settings: MarketDataSettings) -> None:
        self._service = service
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self.last_stats: IngestStats | None = None

    async def start(self) -> None:
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="market-data-ingest")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        interval_s = self._settings.ingest_interval_seconds
        while not self._stopped.is_set():
            try:
                self.last_stats = await self._service.ingest_once()
            except Exception:
                logger.exception("pasada de ingest de market-data falló")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=interval_s)
            except TimeoutError:
                continue


__all__ = ["IngestPoller", "IngestService", "IngestStats", "raw_tick_from_quote"]
