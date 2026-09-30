"""main - composición de la aplicación FastAPI del Wallet Service."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from platform_kernel.errors import install_error_handlers
from platform_kernel.idempotency import build_idempotency_store
from platform_kernel.logging import setup_logging
from platform_kernel.metrics import MetricsMiddleware, metrics_response
from platform_kernel.middleware import RequestContextMiddleware
from platform_kernel.telemetry import init_telemetry, instrument_app

from wallet.config import get_wallet_settings
from wallet.db import get_engine, reset_engine
from wallet.routes import router

logger = logging.getLogger("wallet")

#: locks de transferencia por franja (serialización A→B por usuario, por proceso)
TRANSFER_LOCK_STRIPES = 64


def create_app(*, auto_migrate: bool | None = None) -> FastAPI:
    settings = get_wallet_settings()
    setup_logging(settings.service_name, settings.log_level)
    init_telemetry(settings.otel_endpoint, service_name=settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        do_migrate = settings.environment in ("local", "test") if auto_migrate is None else auto_migrate
        if do_migrate:
            from wallet.migrate import run_migrations

            await asyncio.to_thread(run_migrations, settings.wallet_database_url)
        app.state.idempotency = await build_idempotency_store(settings.redis_url)
        # costuras para tests: se sustituyen por dobles HTTP (patrón accounts)
        app.state.ledger_client = None
        app.state.accounts_client = None
        app.state.transfer_locks = [asyncio.Lock() for _ in range(TRANSFER_LOCK_STRIPES)]

        from wallet.db import get_session_factory

        consumer = None
        if settings.event_consumer_enabled:
            from wallet.consumer import WalletEventConsumer

            consumer = WalletEventConsumer(get_session_factory(), settings)
            await consumer.start()
        app.state.event_consumer = consumer

        reconciler = None
        if settings.reconcile_interval_seconds > 0:
            from wallet.reconciler import Reconciler

            reconciler = Reconciler(get_session_factory(), settings)
            await reconciler.start()
        app.state.reconciler = reconciler

        logger.info("wallet listo", extra={"extra_fields": {"environment": settings.environment}})
        yield
        if reconciler is not None:
            await reconciler.stop()
        if consumer is not None:
            await consumer.stop()
        engine = get_engine()
        await engine.dispose()
        reset_engine()

    app = FastAPI(
        title="MonedasAR Wallet Service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment in ("local", "development") else None,
        redoc_url=None,
    )
    app.include_router(router)
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

    settings = get_wallet_settings()
    uvicorn.run(
        "wallet.main:app",
        host="0.0.0.0",
        port=8087,
        reload=settings.environment == "local",
        loop="platform_kernel.loop_factory:selector_loop_factory",
    )


__all__ = ["app", "create_app", "run"]
