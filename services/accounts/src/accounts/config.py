"""config - ajustes del Accounts Service (Q-api-map §2.4, BUILD-020/023)."""

from __future__ import annotations

from functools import lru_cache

from platform_kernel.config import KernelSettings
from pydantic_settings import SettingsConfigDict


class AccountsSettings(KernelSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    service_name: str = "accounts"
    # 127.0.0.1 evita el intento previo a ::1 (IPv6) que en Windows+Docker tarda ~2s por conexión
    accounts_database_url: str = (
        "postgresql+psycopg://platform:platform_local_dev_only@127.0.0.1:5433/platform_accounts"
    )

    identity_url: str = "http://127.0.0.1:8081"
    identity_timeout_seconds: float = 5.0

    #: Saldo/cierre leen la fuente de verdad (Q §3); la escritura es event-driven (#16/#17).
    ledger_url: str = "http://127.0.0.1:8085"
    ledger_timeout_seconds: float = 5.0

    redpanda_bootstrap_servers: str = "127.0.0.1:19092"

    outbox_relay_enabled: bool = True
    outbox_relay_interval_ms: int = 500
    outbox_max_attempts: int = 5
    outbox_batch_size: int = 100

    event_consumer_enabled: bool = True

    demo_currency: str = "USD"
    #: Saldo inicial de la cuenta demo (S-mvp-scope: "ej. USD 10.000").
    demo_initial_balance: str = "10000"

    flag_live_trading: bool = False  # jamás true sin licencia (ADR-0012)


@lru_cache(maxsize=1)
def get_accounts_settings() -> AccountsSettings:
    settings = AccountsSettings()  # type: ignore[call-arg]
    if settings.flag_live_trading:
        raise ValueError("flag_live_trading debe permanecer false: requiere licencia (ADR-0012)")
    return settings


__all__ = ["AccountsSettings", "get_accounts_settings"]
