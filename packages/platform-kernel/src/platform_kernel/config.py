"""config — ajustes comunes a todos los servicios (inyección por variables de entorno)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "development", "staging", "uat", "production"]

DEV_JWT_SECRET = "local-development-only-jwt-secret-do-not-use-outside-local"
DEV_SERVICE_TOKEN_SECRET = "local-development-only-service-token-secret-not-for-prod"


class KernelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    service_name: str = "unknown"
    environment: Environment = "local"
    log_level: str = "INFO"

    jwt_secret: str = DEV_JWT_SECRET
    jwt_issuer: str = "platform-identity"
    jwt_audience: str = "platform-api"
    access_token_ttl_seconds: int = Field(default=900, le=900)  # ≤15 min (ADR-0008)
    service_token_secret: str = DEV_SERVICE_TOKEN_SECRET
    service_token_audience: str = "platform-internal"

    redis_url: str | None = None
    otel_endpoint: str | None = None

    cors_origins: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _production_requires_real_secrets(self) -> KernelSettings:
        if self.environment == "production":
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET real (>=32 chars) obligatorio en production")
            if self.service_token_secret == DEV_SERVICE_TOKEN_SECRET:
                raise ValueError("SERVICE_TOKEN_SECRET real obligatorio en production")
        return self


@lru_cache(maxsize=4)
def get_settings() -> KernelSettings:
    return KernelSettings()  # type: ignore[call-arg]


__all__ = ["DEV_JWT_SECRET", "DEV_SERVICE_TOKEN_SECRET", "Environment", "KernelSettings", "get_settings"]
