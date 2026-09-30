"""main — composición de la aplicación FastAPI del Ledger Service."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from platform_kernel.errors import install_error_handlers
from platform_kernel.logging import setup_logging
from platform_kernel.metrics import MetricsMiddleware, metrics_response
from platform_kernel.middleware import RequestContextMiddleware
from platform_kernel.telemetry import init_telemetry, instrument_app

from ledger.config import get_ledger_settings
from ledger.db import get_engine, reset_engine
from ledger.public import router as public_router
from ledger.routes import router

logger = logging.getLogger("ledger")


def create_app(*, auto_migrate: bool | None = None) -> FastAPI:
    settings = get_ledger_settings()
    setup_logging(settings.service_name, settings.log_level)
    init_telemetry(settings.otel_endpoint, service_name=settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        do_migrate = settings.environment in ("local", "test") if auto_migrate is None else auto_migrate
        if do_migrate:
            from ledger.migrate import run_migrations

            await asyncio.to_thread(run_migrations, settings.ledger_database_url)
        relay = None
        if settings.outbox_relay_enabled:
            from ledger.db import get_session_factory
            from ledger.outbox import OutboxRelay

            relay = OutboxRelay(get_session_factory(), settings)
            await relay.start()
        app.state.relay = relay

        consumer = None
        if settings.event_consumer_enabled:
            from ledger.consumer import LedgerEventConsumer
            from ledger.db import get_session_factory

            consumer = LedgerEventConsumer(get_session_factory(), settings)
            await consumer.start()
        app.state.event_consumer = consumer
        logger.info("ledger listo", extra={"extra_fields": {"environment": settings.environment}})
        yield
        if consumer is not None:
            await consumer.stop()
        if relay is not None:
            await relay.stop()
        await get_engine().dispose()
        reset_engine()

    app = FastAPI(
        title="MonedasAR Ledger Service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment in ("local", "development") else None,
        redoc_url=None,
    )
    app.include_router(router)
    app.include_router(public_router)
    app.add_middleware(MetricsMiddleware, service=settings.service_name)
    app.add_middleware(RequestContextMiddleware, trust_client_request_id=True)
    install_error_handlers(app)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():  # type: ignore[no-untyped-def]
        return metrics_response()

    instrument_app(app)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_ledger_settings()
    uvicorn.run(
        "ledger.main:app",
        host="0.0.0.0",
        port=8085,
        reload=settings.environment == "local",
        loop="platform_kernel.loop_factory:selector_loop_factory",
    )


__all__ = ["app", "create_app", "run"]
