"""config — ajustes específicos del Identity Service."""

from __future__ import annotations

from functools import lru_cache

from platform_kernel.config import KernelSettings
from pydantic import Field
from pydantic_settings import SettingsConfigDict


class IdentitySettings(KernelSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    service_name: str = "identity"
    # 127.0.0.1 evita el intento previo a ::1 (IPv6) que en Windows+Docker tarda ~2s por conexión
    database_url: str = "postgresql+psycopg://platform:platform_local_dev_only@127.0.0.1:5433/platform_identity"

    redpanda_bootstrap_servers: str = "127.0.0.1:19092"

    require_email_verification: bool = True
    trust_proxy_headers: bool = True  # en compose el gateway es el único entrypoint (ADR-0017)
    refresh_ttl_days: int = Field(default=30, ge=1, le=365)
    login_max_failures: int = 10
    lockout_minutes: int = 15

    rate_limit_login_per_minute: int = 10
    rate_limit_ip_per_minute: int = 30
    rate_limit_register_per_minute: int = 5
    rate_limit_forgot_per_hour: int = 5

    flag_mfa: bool = False  # feature flag MFA TOTP (ADR-0012)
    flag_live_trading: bool = False  # jamás true en Fase 1 (ADR-0012)

    outbox_relay_enabled: bool = True
    outbox_relay_interval_ms: int = Field(default=500, ge=50)
    outbox_max_attempts: int = Field(default=5, ge=1)
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)

    @property
    def verification_ttl_hours(self) -> int:
        return 24


@lru_cache(maxsize=1)
def get_identity_settings() -> IdentitySettings:
    settings = IdentitySettings()  # type: ignore[call-arg]
    if settings.flag_live_trading:
        raise ValueError("flag_live_trading debe permanecer false: requiere licencia (ADR-0012)")
    return settings


__all__ = ["IdentitySettings", "get_identity_settings"]
