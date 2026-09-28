"""main — composición de la aplicación FastAPI del Identity Service."""

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
from platform_kernel.ratelimit import build_rate_limiter

from identity.config import get_identity_settings
from identity.db import get_engine, reset_engine
from identity.outbox import OutboxDispatcher
from identity.routes import router

logger = logging.getLogger("identity")


def create_app(*, auto_migrate: bool | None = None) -> FastAPI:
    settings = get_identity_settings()
    setup_logging(settings.service_name, settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        do_migrate = settings.environment in ("local", "test") if auto_migrate is None else auto_migrate
        if do_migrate:
            from identity.migrate import run_migrations

            await asyncio.to_thread(run_migrations, settings.database_url)
        app.state.limiter = await build_rate_limiter(settings.redis_url)
        app.state.idempotency = await build_idempotency_store(settings.redis_url)
        from identity.db import get_session_factory

        dispatcher = OutboxDispatcher(get_session_factory(), settings)
        await dispatcher.start()
        app.state.dispatcher = dispatcher
        logger.info("identity listo", extra={"extra_fields": {"environment": settings.environment}})
        yield
        await dispatcher.stop()
        engine = get_engine()
        await engine.dispose()
        reset_engine()

    app = FastAPI(
        title="[PROJECT_NAME] Identity Service",
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
            expose_headers=["X-Request-Id", "X-Correlation-Id", "Idempotent-Replay"],
        )
    app.add_middleware(RequestContextMiddleware, trust_client_request_id=True)
    install_error_handlers(app)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():  # type: ignore[no-untyped-def]
        return metrics_response()

    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_identity_settings()
    uvicorn.run(
        "identity.main:app",
        host="0.0.0.0",
        port=8081,
        reload=settings.environment == "local",
        loop="platform_kernel.loop_factory:selector_loop_factory",
    )


__all__ = ["app", "create_app", "run"]
