"""factory — selección del driver canónico por settings (K §1.1, BUILD-026).

El núcleo consume `MarketDataProvider`; cambiar de driver es un cambio de
configuración, no de código. Hoy solo existe el mock (etiqueta `simulated`);
los drivers reales exigen el gate X-07 (contrato + redistribución).
"""

from __future__ import annotations

from market_data.config import MarketDataSettings
from market_data.domain.protocols import MarketDataProvider
from market_data.providers.mock import MockMarketDataProvider


def create_market_data_provider(settings: MarketDataSettings) -> MarketDataProvider:
    if settings.provider_driver == "mock":
        return MockMarketDataProvider(seed=settings.mock_provider_seed)
    raise ValueError(f"market-data: provider_driver desconocido: {settings.provider_driver!r}")


__all__ = ["create_market_data_provider"]
