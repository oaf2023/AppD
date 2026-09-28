"""config — ajustes del Audit Service."""

from __future__ import annotations

from functools import lru_cache

from platform_kernel.config import KernelSettings
from pydantic_settings import SettingsConfigDict


class AuditSettings(KernelSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    service_name: str = "audit"
    audit_database_url: str = "postgresql+psycopg://platform:platform_local_dev_only@localhost:5433/platform_audit"
    page_size_default: int = 50
    page_size_max: int = 200


@lru_cache(maxsize=1)
def get_audit_settings() -> AuditSettings:
    return AuditSettings()  # type: ignore[call-arg]


__all__ = ["AuditSettings", "get_audit_settings"]
