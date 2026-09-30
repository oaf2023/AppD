"""conftest de pruebas de integración (ASGI en proceso, con lifespan real)."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

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
async def accounts_app(clean_dbs: None):  # type: ignore[no-untyped-def]
    """Accounts con lifespan real; `identity` y `ledger` doblados con MockTransport.

    Estado controlable por test:
    - `app.state.identity_client` → perfil (jurisdicción ES);
    - `app.state.ledger_balances` → `{(user_id_str, currency): saldo}` para
      `GET /internal/v1/balances` (cierre/recarga, Q §3).

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
            app.state.ledger_balances: dict[tuple[str, str], Decimal | str] = {}

            def _ledger_mock(request: httpx.Request) -> httpx.Response:
                if request.url.path == "/internal/v1/balances":
                    owner = request.url.params.get("owner_id")
                    rows = [
                        {"owner_id": user_id, "currency": currency, "balance": str(balance)}
                        for (user_id, currency), balance in app.state.ledger_balances.items()
                        if owner is None or user_id == owner
                    ]
                    return httpx.Response(200, json={"data": rows, "as_of": "2026-09-30T00:00:00+00:00"})
                return httpx.Response(404, json={"detail": "ruta no mockeada"})

            app.state.identity_client = httpx.AsyncClient(transport=httpx.MockTransport(_identity_mock))
            app.state.ledger_client = httpx.AsyncClient(transport=httpx.MockTransport(_ledger_mock))
            try:
                yield app
            finally:
                await app.state.identity_client.aclose()
                await app.state.ledger_client.aclose()
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


@pytest.fixture
async def accounts_client(accounts_app):  # type: ignore[no-untyped-def]
    import httpx

    transport = httpx.ASGITransport(app=accounts_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as client:
        yield client


@pytest.fixture
async def wallet_app(clean_dbs: None):  # type: ignore[no-untyped-def]
    """Wallet con lifespan real; ledger y accounts doblados con MockTransport.

    Estado controlable por test:
    - `app.state.ledger_balances` → `{(user_id_str, currency): saldo}` (GET balances);
    - `app.state.ledger_postings` → capturas de `POST /internal/v1/postings`;
    - `app.state.accounts_map` → `{account_id_str: dict}` (GET accounts, BOLA).
    """
    import httpx
    from wallet.config import get_wallet_settings
    from wallet.db import reset_engine

    previous_consumer = os.environ.get("EVENT_CONSUMER_ENABLED")
    os.environ["EVENT_CONSUMER_ENABLED"] = "false"
    get_wallet_settings.cache_clear()
    reset_engine()

    from wallet.main import create_app

    try:
        app = create_app()
        async with app.router.lifespan_context(app):
            app.state.ledger_balances: dict[tuple[str, str], Decimal | str] = {}
            app.state.ledger_postings: list[dict] = []
            app.state.accounts_map: dict[str, dict] = {}

            def _ledger_mock(request: httpx.Request) -> httpx.Response:
                if request.method == "GET" and request.url.path == "/internal/v1/balances":
                    owner = request.url.params.get("owner_id")
                    rows = [
                        {"owner_id": user_id, "currency": currency, "balance": str(balance)}
                        for (user_id, currency), balance in app.state.ledger_balances.items()
                        if owner is None or user_id == owner
                    ]
                    return httpx.Response(200, json={"data": rows, "as_of": "2026-09-30T00:00:00+00:00"})
                if request.method == "POST" and request.url.path == "/internal/v1/postings":
                    import json as _json

                    body = _json.loads(request.content)
                    app.state.ledger_postings.append(body)
                    return httpx.Response(201, json={"transaction_id": str(uuid.uuid4()), **body})
                return httpx.Response(404, json={"detail": "ruta no mockeada"})

            def _accounts_mock(request: httpx.Request) -> httpx.Response:
                account_id = request.url.path.rsplit("/", 1)[-1]
                account = app.state.accounts_map.get(account_id)
                if account is None:
                    return httpx.Response(404, json={"detail": "cuenta no encontrada"})
                return httpx.Response(200, json=account)

            app.state.ledger_client = httpx.AsyncClient(transport=httpx.MockTransport(_ledger_mock))
            app.state.accounts_client = httpx.AsyncClient(transport=httpx.MockTransport(_accounts_mock))
            try:
                yield app
            finally:
                await app.state.ledger_client.aclose()
                await app.state.accounts_client.aclose()
    finally:
        if previous_consumer is None:
            os.environ.pop("EVENT_CONSUMER_ENABLED", None)
        else:
            os.environ["EVENT_CONSUMER_ENABLED"] = previous_consumer
        get_wallet_settings.cache_clear()
        reset_engine()


@pytest.fixture
async def wallet_client(wallet_app):  # type: ignore[no-untyped-def]
    import httpx

    transport = httpx.ASGITransport(app=wallet_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=30.0) as client:
        yield client
