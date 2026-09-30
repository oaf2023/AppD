"""config - ajustes del Wallet Service (Q-api-map §2.5, BUILD-019/021/022)."""

from __future__ import annotations

from functools import lru_cache

from platform_kernel.config import KernelSettings
from pydantic_settings import SettingsConfigDict


class WalletSettings(KernelSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    service_name: str = "wallet"
    # 127.0.0.1 evita el intento previo a ::1 (IPv6 que en Windows+Docker tarda ~2s por conexión)
    wallet_database_url: str = "postgresql+psycopg://platform:platform_local_dev_only@127.0.0.1:5433/platform_wallet"

    ledger_url: str = "http://127.0.0.1:8085"
    accounts_url: str = "http://127.0.0.1:8086"
    ledger_timeout_seconds: float = 5.0
    accounts_timeout_seconds: float = 5.0

    redpanda_bootstrap_servers: str = "127.0.0.1:19092"

    event_consumer_enabled: bool = True

    #: Intervalo del reconciliador ledger↔wallet en segundos; 0 = deshabilitado (BUILD-019).
    reconcile_interval_seconds: int = 60


@lru_cache(maxsize=1)
def get_wallet_settings() -> WalletSettings:
    return WalletSettings()  # type: ignore[call-arg]


__all__ = ["WalletSettings", "get_wallet_settings"]
