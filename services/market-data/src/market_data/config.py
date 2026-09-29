"""config — ajustes del Market Data Service.

Sin secretos: todos los proveedores son keyless (docs/API_INTEGRATIONS.md).
"""

from __future__ import annotations

from functools import lru_cache

from platform_kernel.config import KernelSettings
from pydantic_settings import SettingsConfigDict


class MarketDataSettings(KernelSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    service_name: str = "market-data"

    # Proveedores keyless verificados (2026-09-28) — cero credenciales por diseño
    frankfurter_base_url: str = "https://api.frankfurter.dev/v2"
    ecb_base_url: str = "https://data-api.ecb.europa.eu/service/data"
    kraken_base_url: str = "https://api.kraken.com"
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"

    http_timeout_seconds: float = 5.0
    # FX: referencia diaria del BCE (~16:00 CET) → TTL holgado
    fx_cache_ttl_seconds: int = 900
    # Crypto: Kraken limita 1 req/s por IP → un batch cada 60s bien dentro del límite
    crypto_cache_ttl_seconds: int = 60

    breaker_failure_threshold: int = 3
    breaker_cooldown_seconds: float = 30.0


@lru_cache(maxsize=1)
def get_market_data_settings() -> MarketDataSettings:
    return MarketDataSettings()  # type: ignore[call-arg]


__all__ = ["MarketDataSettings", "get_market_data_settings"]
