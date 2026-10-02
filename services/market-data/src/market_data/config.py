"""config — ajustes del Market Data Service.

Sin secretos: todos los proveedores son keyless (docs/API_INTEGRATIONS.md).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

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

    # Driver del contrato canónico (K §1.1, BUILD-026): por defecto el mock
    # determinista etiquetado simulated; drivers reales solo con gate X-07.
    provider_driver: Literal["mock"] = "mock"
    mock_provider_seed: int = 42

    # Persistencia de mercado (K §4.4, BUILD-027): schema `market_data` dedicado
    # (O-database-strategy §2); Postgres 17 plano, TimescaleDB/retención = DECIDIR.
    market_data_database_url: str = (
        "postgresql+psycopg://platform:platform_local_dev_only@127.0.0.1:5433/platform_market_data"
    )
    # Ingesta desde el driver canónico: apagada por defecto (determinismo de
    # tests y arranques mínimos); el deploy local/OMV la activa explícitamente.
    ingest_enabled: bool = False
    ingest_interval_seconds: float = 5.0

    # Modo del hub (R §1): `live_trading=false` ⇒ todo payload `DEMO`.
    flag_live_trading: bool = False

    # Bus Redpanda + relay del outbox `SymbolUpdated` (K §4.2, BUILD-029).
    # El relay va apagado por defecto (mismo criterio que `ingest_enabled`);
    # el deploy local/OMV lo activa explícitamente con `OUTBOX_RELAY_ENABLED`.
    redpanda_bootstrap_servers: str = "127.0.0.1:19092"
    outbox_relay_enabled: bool = False
    outbox_relay_interval_ms: int = 500
    outbox_max_attempts: int = 5
    outbox_batch_size: int = 100

    # Hub WebSocket interno `/ws/v1` (R-websocket-map §2/§3/§5, BUILD-029).
    ws_auth_timeout_seconds: float = 5.0
    ws_heartbeat_interval_seconds: float = 20.0
    ws_idle_timeout_seconds: float = 120.0
    ws_ring_max_messages: int = 1000
    ws_ring_max_age_seconds: int = 300
    ws_max_subscriptions: int = 50
    ws_max_connections_per_user: int = 5
    ws_max_connections_per_ip: int = 50
    ws_frames_per_second: int = 20
    ws_frames_per_minute: int = 60
    ws_subscribe_per_minute: int = 30
    ws_queue_max_frames: int = 1000
    ws_frame_max_bytes: int = 65536
    ws_string_max_bytes: int = 1024
    ws_ping_min_interval_seconds: float = 5.0
    #: Orígenes `Origin` permitidos (R §6); vacío = sin restricción.
    ws_allowed_origins: str = ""

    @property
    def ws_allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ws_allowed_origins.split(",") if o.strip()]

    @property
    def ws_mode(self) -> str:
        return "LIVE" if self.flag_live_trading else "DEMO"


@lru_cache(maxsize=1)
def get_market_data_settings() -> MarketDataSettings:
    return MarketDataSettings()  # type: ignore[call-arg]


__all__ = ["MarketDataSettings", "get_market_data_settings"]
