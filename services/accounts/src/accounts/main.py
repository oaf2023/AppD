"""main — composición de la aplicación FastAPI del Accounts Service."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from platform_kernel.errors import install_error_handlers
from platform_kernel.idempotency import build_idempotency_store
from platform_kernel.logging import setup_logging
from platform_kernel.metrics import MetricsMiddleware, metrics_response
from platform_kernel.middleware import RequestContextMiddleware
from platform_kernel.telemetry import init_telemetry, instrument_app

from accounts.config import get_accounts_settings
from accounts.db import get_engine, reset_engine
from accounts.outbox import OutboxRelay
from accounts.routes import router

logger = logging.getLogger("accounts")


def create_app(*, auto_migrate: bool | None = None) -> FastAPI:
    settings = get_accounts_settings()
    setup_logging(settings.service_name, settings.log_level)
    init_telemetry(settings.otel_endpoint, service_name=settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        do_migrate = settings.environment in ("local", "test") if auto_migrate is None else auto_migrate
        if do_migrate:
            from accounts.migrate import run_migrations

            await asyncio.to_thread(run_migrations, settings.accounts_database_url)
        app.state.idempotency = await build_idempotency_store(settings.redis_url)
        # Cliente HTTP hacia identity (Q §3); los tests lo sustituyen por un doble.
        app.state.identity_client = None
        # Cliente HTTP hacia ledger (saldo en cierre/recarga, Q §3); costura de tests.
        app.state.ledger_client = None

        from accounts.db import get_session_factory

        relay: OutboxRelay | None = None
        if settings.outbox_relay_enabled:
            relay = OutboxRelay(get_session_factory(), settings)
            await relay.start()
        app.state.relay = relay

        consumer = None
        if settings.event_consumer_enabled:
            from accounts.consumer import AccountsEventConsumer

            consumer = AccountsEventConsumer(get_session_factory(), settings)
            await consumer.start()
        app.state.event_consumer = consumer
        logger.info("accounts listo", extra={"extra_fields": {"environment": settings.environment}})
        yield
        if consumer is not None:
            await consumer.stop()
        if relay is not None:
            await relay.stop()
        engine = get_engine()
        await engine.dispose()
        reset_engine()

    app = FastAPI(
        title="MonedasAR Accounts Service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment in ("local", "development") else None,
        redoc_url=None,
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
            expose_headers=["X-Request-Id", "X-Correlation-Id", "Idempotent-Replay", "Location"],
        )
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

    settings = get_accounts_settings()
    uvicorn.run(
        "accounts.main:app",
        host="0.0.0.0",
        port=8086,
        reload=settings.environment == "local",
        loop="platform_kernel.loop_factory:selector_loop_factory",
    )


__all__ = ["app", "create_app", "run"]
