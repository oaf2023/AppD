"""main — aplicación FastAPI del Gateway."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from platform_kernel.errors import install_error_handlers
from platform_kernel.logging import setup_logging
from platform_kernel.metrics import MetricsMiddleware
from platform_kernel.middleware import RequestContextMiddleware
from platform_kernel.ratelimit import build_rate_limiter
from platform_kernel.telemetry import init_telemetry, instrument_app

from gateway.config import get_gateway_settings
from gateway.proxy import router

logger = logging.getLogger("gateway")


def create_app() -> FastAPI:
    settings = get_gateway_settings()
    setup_logging(settings.service_name, settings.log_level)
    init_telemetry(settings.otel_endpoint, service_name=settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.limiter = await build_rate_limiter(settings.redis_url)
        app.state.client = httpx.AsyncClient(timeout=settings.proxy_timeout_seconds)
        logger.info("gateway listo", extra={"extra_fields": {"environment": settings.environment}})
        yield
        await app.state.client.aclose()

    app = FastAPI(
        title="[PROJECT_NAME] API Gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(router)
    app.add_middleware(MetricsMiddleware, service=settings.service_name)
    if settings.cors_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-Id", "X-Correlation-Id", "Idempotent-Replay", "RateLimit-Limit"],
        )
    app.add_middleware(RequestContextMiddleware, trust_client_request_id=False)
    install_error_handlers(app)
    instrument_app(app)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_gateway_settings()
    uvicorn.run(
        "gateway.main:app",
        host="0.0.0.0",
        port=8080,
        reload=settings.environment == "local",
        loop="platform_kernel.loop_factory:selector_loop_factory",
    )


__all__ = ["app", "create_app", "run"]
