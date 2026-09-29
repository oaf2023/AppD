"""service — orquestación de proveedores: cache TTL, failover y cortacircuitos.

Regla no-ficción (K §6.1): jamás se fabrica un precio. Si todo falla se sirve el
último snapshot bueno con `stale=true`; si nunca hubo dato, la clase queda
`unavailable` y la portada muestra "dato no disponible".
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from platform_contracts.market_data import MarketClassOverview, MarketOverview, OverviewQuote

from market_data.config import MarketDataSettings
from market_data.domain.protocols import AssetClass, MarketDataProvider, ProviderError, Quote
from market_data.infrastructure.breaker import CircuitBreaker
from market_data.providers import CoinGeckoProvider, EcbProvider, FrankfurterProvider, KrakenProvider

logger = logging.getLogger("market_data.service")

_TTL_BY_CLASS: dict[AssetClass, str] = {"forex": "fx_cache_ttl_seconds", "crypto": "crypto_cache_ttl_seconds"}


def default_providers(settings: MarketDataSettings) -> list[MarketDataProvider]:
    """Orden de failover: FX = Frankfurter → ECB directo; Crypto = Kraken → CoinGecko."""
    return [
        FrankfurterProvider(settings.frankfurter_base_url),
        EcbProvider(settings.ecb_base_url),
        KrakenProvider(settings.kraken_base_url),
        CoinGeckoProvider(settings.coingecko_base_url),
    ]


@dataclass(frozen=True, slots=True)
class _Snapshot:
    quotes: dict[str, Quote]
    fetched_at: datetime
    provider_id: str
    source: str
    attribution: str | None


@dataclass(frozen=True, slots=True)
class _Plan:
    asset_class: AssetClass
    ttl_seconds: int
    providers: tuple[MarketDataProvider, ...]


class MarketDataService:
    def __init__(
        self,
        settings: MarketDataSettings,
        client: httpx.AsyncClient,
        *,
        providers: list[MarketDataProvider] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(UTC))
        self._snapshots: dict[AssetClass, _Snapshot] = {}

        selected = providers if providers is not None else default_providers(settings)
        grouped: dict[AssetClass, list[MarketDataProvider]] = {"forex": [], "crypto": []}
        for provider in selected:
            grouped[provider.asset_class].append(provider)
        self._plans: dict[AssetClass, _Plan] = {
            asset_class: _Plan(
                asset_class=asset_class,
                ttl_seconds=int(getattr(settings, _TTL_BY_CLASS[asset_class])),
                providers=tuple(grouped[asset_class]),
            )
            for asset_class in ("forex", "crypto")
        }
        self._breakers: dict[str, CircuitBreaker] = {
            provider.provider_id: CircuitBreaker(
                settings.breaker_failure_threshold,
                settings.breaker_cooldown_seconds,
            )
            for provider in selected
        }

    async def overview(self) -> MarketOverview:
        forex, crypto = await asyncio.gather(
            self._resolve(self._plans["forex"]),
            self._resolve(self._plans["crypto"]),
        )
        fetched = [snap.fetched_at for snap in self._snapshots.values()]
        return MarketOverview(as_of=max(fetched) if fetched else None, classes=[forex, crypto])

    async def _resolve(self, plan: _Plan) -> MarketClassOverview:
        snapshot = self._snapshots.get(plan.asset_class)
        now = self._clock()
        if snapshot is not None and (now - snapshot.fetched_at).total_seconds() <= plan.ttl_seconds:
            return self._build(plan.asset_class, snapshot, stale=False)

        for provider in plan.providers:
            breaker = self._breakers[provider.provider_id]
            if not breaker.available():
                continue
            try:
                quotes = await provider.fetch_quotes(self._client)
            except (httpx.HTTPError, ProviderError, ValueError) as exc:
                breaker.record_failure()
                logger.warning(
                    "proveedor %s falló: %s",
                    provider.provider_id,
                    exc,
                    extra={"extra_fields": {"provider": provider.provider_id}},
                )
                continue
            breaker.record_success()
            fresh = _Snapshot(
                quotes=quotes,
                fetched_at=self._clock(),
                provider_id=provider.provider_id,
                source=provider.source,
                attribution=provider.attribution,
            )
            self._snapshots[plan.asset_class] = fresh
            return self._build(plan.asset_class, fresh, stale=False)

        if snapshot is not None:
            # Último dato bueno (K §6.1): se sirve con stale=true, nunca inventado
            return self._build(plan.asset_class, snapshot, stale=True)
        logger.warning(
            "clase %s sin datos: todos los proveedores fallaron o están abiertos",
            plan.asset_class,
            extra={"extra_fields": {"asset_class": plan.asset_class}},
        )
        return MarketClassOverview(asset_class=plan.asset_class, status="unavailable", instruments=[])

    @staticmethod
    def _build(asset_class: AssetClass, snapshot: _Snapshot, *, stale: bool) -> MarketClassOverview:
        instruments = [
            OverviewQuote(
                symbol=quote.symbol,
                value=quote.value,
                ts=quote.ts,
                source=snapshot.source,
                provider=snapshot.provider_id,
                stale=stale,
                simulated=False,
                attribution=snapshot.attribution,
            )
            for quote in sorted(snapshot.quotes.values(), key=lambda q: q.symbol)
        ]
        return MarketClassOverview(
            asset_class=asset_class,
            status="stale" if stale else "available",
            instruments=instruments,
        )


__all__ = ["MarketDataService", "default_providers"]
