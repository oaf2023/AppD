"""config — ajustes del Gateway."""

from __future__ import annotations

from functools import lru_cache

from platform_kernel.config import KernelSettings
from pydantic_settings import SettingsConfigDict


class GatewaySettings(KernelSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    service_name: str = "gateway"
    # 127.0.0.1 evita el intento previo a ::1 (IPv6) que en Windows+Docker tarda ~2s por conexión
    identity_url: str = "http://127.0.0.1:8081"
    audit_url: str = "http://127.0.0.1:8083"
    market_data_url: str = "http://127.0.0.1:8084"
    ledger_url: str = "http://127.0.0.1:8085"

    rate_limit_global_per_minute: int = 120
    rate_limit_auth_per_minute: int = 30
    proxy_timeout_seconds: float = 15.0

    # Rutas de autenticación que se limitan con una clave más estricta
    auth_prefixes: tuple[str, ...] = ("/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/mfa")


@lru_cache(maxsize=1)
def get_gateway_settings() -> GatewaySettings:
    return GatewaySettings()  # type: ignore[call-arg]


__all__ = ["GatewaySettings", "get_gateway_settings"]
