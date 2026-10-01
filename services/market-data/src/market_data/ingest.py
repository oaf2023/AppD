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
   `gap=true` (K §4.4(c), nunca fabricados).

`IngestPoller` repite el ciclo cada `ingest_interval_seconds` **solo si**
`ingest_enabled` (apagado por defecto; el deploy lo activa). Sin Redpanda aún:
el bus llega con BUILD-029/030 — desviación documentada en K §4.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from platform_kernel.clock import utcnow
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from market_data.config import MarketDataSettings
from market_data.domain.models import CanonicalDataError, Quote, Tick
from market_data.domain.protocols import MarketDataProvider, ProviderError
from market_data.normalization import RawTick, normalize_tick
from market_data.store import (
    bucket_start_1m,
    gap_candidates_between,
    insert_ticks,
    mark_gap_candles,
    max_tick_ts,
    recompute_candles_1m,
)

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
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._clock = clock

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
            for symbol, symbol_ticks in by_symbol.items():
                prior_ts = await max_tick_ts(session, symbol)
                inserted_ts = await insert_ticks(session, symbol_ticks)
                stats.inserted += len(inserted_ts)
                stats.duplicates += len(symbol_ticks) - len(inserted_ts)
                if not inserted_ts:
                    continue
                stats.symbols.add(symbol)
                buckets = sorted({bucket_start_1m(ts) for ts in inserted_ts})
                await recompute_candles_1m(session, symbol, buckets)
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
        return stats


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
