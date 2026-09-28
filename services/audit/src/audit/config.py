"""config — ajustes del Audit Service."""

from __future__ import annotations

from functools import lru_cache

from platform_kernel.config import KernelSettings
from pydantic_settings import SettingsConfigDict


class AuditSettings(KernelSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    service_name: str = "audit"
    # 127.0.0.1 evita el intento previo a ::1 (IPv6) que en Windows+Docker tarda ~2s por conexión
    audit_database_url: str = "postgresql+psycopg://platform:platform_local_dev_only@127.0.0.1:5433/platform_audit"
    page_size_default: int = 50
    page_size_max: int = 200

    redpanda_bootstrap_servers: str = "127.0.0.1:19092"
    event_consumer_enabled: bool = True


@lru_cache(maxsize=1)
def get_audit_settings() -> AuditSettings:
    return AuditSettings()  # type: ignore[call-arg]


__all__ = ["AuditSettings", "get_audit_settings"]
