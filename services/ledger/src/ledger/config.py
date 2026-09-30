"""config - ajustes del Ledger Service (L-ledger-architecture.md, ADR-0010)."""

from __future__ import annotations

from functools import lru_cache

from platform_kernel.config import KernelSettings
from pydantic_settings import SettingsConfigDict

#: Retención de las claves de idempotencia: 7 días (L §6).
IDEMPOTENCY_TTL_SECONDS = 604800


class LedgerSettings(KernelSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    service_name: str = "ledger"
    # 127.0.0.1 evita el intento previo a ::1 (IPv6) que en Windows+Docker tarda ~2s por conexión
    ledger_database_url: str = "postgresql+psycopg://platform:platform_local_dev_only@127.0.0.1:5433/platform_ledger"

    redpanda_bootstrap_servers: str = "127.0.0.1:19092"

    outbox_relay_enabled: bool = True
    outbox_relay_interval_ms: int = 500
    outbox_max_attempts: int = 5
    outbox_batch_size: int = 100

    event_consumer_enabled: bool = True

    idempotency_ttl_seconds: int = IDEMPOTENCY_TTL_SECONDS


@lru_cache(maxsize=1)
def get_ledger_settings() -> LedgerSettings:
    return LedgerSettings()  # type: ignore[call-arg]


__all__ = ["IDEMPOTENCY_TTL_SECONDS", "LedgerSettings", "get_ledger_settings"]
