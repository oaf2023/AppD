"""main — composición de la aplicación FastAPI del Market Data Service."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from platform_kernel.errors import install_error_handlers
from platform_kernel.logging import setup_logging
from platform_kernel.metrics import MetricsMiddleware, metrics_response
from platform_kernel.middleware import RequestContextMiddleware
from platform_kernel.telemetry import init_telemetry, instrument_app

from market_data.config import MarketDataSettings, get_market_data_settings
from market_data.db import get_engine, get_session_factory, reset_engine
from market_data.ingest import IngestPoller, IngestService
from market_data.providers.factory import create_market_data_provider
from market_data.routes import router
from market_data.service import MarketDataService, default_providers

logger = logging.getLogger("market_data")


def create_app(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    settings: MarketDataSettings | None = None,
    auto_migrate: bool | None = None,
) -> FastAPI:
    cfg = get_market_data_settings() if settings is None else settings
    setup_logging(cfg.service_name, cfg.log_level)
    init_telemetry(cfg.otel_endpoint, service_name=cfg.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        do_migrate = cfg.environment in ("local", "test") if auto_migrate is None else auto_migrate
        if do_migrate:
            from market_data.migrate import run_migrations

            await asyncio.to_thread(run_migrations, cfg.market_data_database_url)
        client = httpx.AsyncClient(timeout=cfg.http_timeout_seconds, transport=transport)
        app.state.settings = cfg
        app.state.service = MarketDataService(cfg, client, providers=default_providers(cfg))
        provider = create_market_data_provider(cfg)
        app.state.market_data_provider = provider
        poller: IngestPoller | None = None
        if cfg.ingest_enabled:
            service = IngestService(get_session_factory(), provider)
            poller = IngestPoller(service, cfg)
            await poller.start()
        app.state.ingest_poller = poller
        logger.info(
            "market-data listo",
            extra={"extra_fields": {"environment": cfg.environment, "ingest_enabled": cfg.ingest_enabled}},
        )
        yield
        if poller is not None:
            await poller.stop()
        await client.aclose()
        engine = get_engine()
        await engine.dispose()
        reset_engine()

    app = FastAPI(
        title="MonedasAR Market Data Service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if cfg.environment in ("local", "development") else None,
        redoc_url=None,
    )
    app.include_router(router)
    app.add_middleware(MetricsMiddleware, service=cfg.service_name)
    if cfg.cors_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-Id", "X-Correlation-Id"],
        )
    app.add_middleware(RequestContextMiddleware, trust_client_request_id=False)
    install_error_handlers(app)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():  # type: ignore[no-untyped-def]
        return metrics_response()

    instrument_app(app)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_market_data_settings()
    uvicorn.run(
        "market_data.main:app",
        host="0.0.0.0",
        port=8084,
        reload=settings.environment == "local",
        loop="platform_kernel.loop_factory:selector_loop_factory",
    )


__all__ = ["app", "create_app", "run"]
