"""helpers — variables de entorno de test y utilidades compartidas.

El módulo fija el entorno al importarse; `tests/conftest.py` lo importa primero,
antes de que cualquier test cargue configuración cacheada de los servicios.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

TEST_JWT_SECRET = "test-jwt-secret-0123456789abcdef0123456789abcdef"
TEST_SERVICE_SECRET = "test-service-secret-0123456789abcdef0123456789abcdef"
TEST_POSTGRES_DSN = "host=127.0.0.1 port=5433 user=platform password=platform_local_dev_only"
TEST_PASSWORD = "Str0ng!Passw0rd-2026"

os.environ.pop("REDIS_URL", None)  # en memoria: sin dependencia de Redis en tests
os.environ.pop("FLAG_LIVE_TRADING", None)
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "LOG_LEVEL": "WARNING",
        "JWT_SECRET": TEST_JWT_SECRET,
        "SERVICE_TOKEN_SECRET": TEST_SERVICE_SECRET,
        "DATABASE_URL": "postgresql+psycopg://platform:platform_local_dev_only@localhost:5433/platform_identity",
        "AUDIT_DATABASE_URL": "postgresql+psycopg://platform:platform_local_dev_only@localhost:5433/platform_audit",
        "AUDIT_SERVICE_URL": "http://127.0.0.1:18083",
        "IDENTITY_URL": "http://127.0.0.1:18081",
        "AUDIT_URL": "http://127.0.0.1:18083",
        "FLAG_MFA": "true",
        "REQUIRE_EMAIL_VERIFICATION": "true",
        # límites generosos: el rate limit se prueba a nivel unitario
        "RATE_LIMIT_REGISTER_PER_MINUTE": "10000",
        "RATE_LIMIT_IP_PER_MINUTE": "10000",
        "RATE_LIMIT_LOGIN_PER_MINUTE": "10000",
        "RATE_LIMIT_FORGOT_PER_HOUR": "10000",
        "RATE_LIMIT_GLOBAL_PER_MINUTE": "10000",
        "RATE_LIMIT_AUTH_PER_MINUTE": "10000",
        "DISPATCHER_INTERVAL_SECONDS": "0.3",
    }
)


def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:16]}@example.com"


@asynccontextmanager
async def lifespan_client(app, base_url: str = "http://testserver") -> AsyncIterator:  # type: ignore[no-untyped-def]
    """Cliente httpx ASGI ejecutando el lifespan real de la app."""
    import httpx

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url, timeout=30.0) as client:
            yield client
