"""conftest de pruebas de integración (ASGI en proceso, con lifespan real)."""

from __future__ import annotations

import os

import pytest
from helpers import lifespan_client


@pytest.fixture
async def identity_client(clean_dbs: None):  # type: ignore[no-untyped-def]
    from identity.main import create_app

    async with lifespan_client(create_app()) as client:
        yield client


@pytest.fixture
async def audit_client(clean_dbs: None):  # type: ignore[no-untyped-def]
    from audit.main import create_app

    async with lifespan_client(create_app()) as client:
        yield client


@pytest.fixture
async def accounts_client(clean_dbs: None):  # type: ignore[no-untyped-def]
    """Accounts con lifespan real; `identity` se dobla con MockTransport (Q §3).

    El relay real necesita Redpanda y el consumidor real se ejercita directo en
    `test_accounts.py`; ambos se deshabilitan SOLO durante este fixture para no
    afectar al resto de la suite.
    """
    import httpx
    from accounts.config import get_accounts_settings
    from accounts.db import reset_engine

    previous_relay = os.environ.get("OUTBOX_RELAY_ENABLED")
    previous_consumer = os.environ.get("EVENT_CONSUMER_ENABLED")
    os.environ["OUTBOX_RELAY_ENABLED"] = "false"
    os.environ["EVENT_CONSUMER_ENABLED"] = "false"
    get_accounts_settings.cache_clear()
    reset_engine()

    def _identity_mock(request: httpx.Request) -> httpx.Response:
        user_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json={"user_id": user_id, "status": "active", "jurisdiction": "ES", "email_verified": True},
        )

    from accounts.main import create_app

    try:
        app = create_app()
        async with app.router.lifespan_context(app):
            app.state.identity_client = httpx.AsyncClient(transport=httpx.MockTransport(_identity_mock))
            try:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as client:
                    yield client
            finally:
                await app.state.identity_client.aclose()
    finally:
        for name, previous in (
            ("OUTBOX_RELAY_ENABLED", previous_relay),
            ("EVENT_CONSUMER_ENABLED", previous_consumer),
        ):
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        get_accounts_settings.cache_clear()
        reset_engine()
