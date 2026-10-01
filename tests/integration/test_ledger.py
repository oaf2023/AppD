"""Pruebas de integración del Ledger Service.

Cubre escritura interna idempotente, invariantes 1/4/5/6/7/9/10 de
`L-ledger-architecture.md` §8, la defensa en profundidad en BD (ADR-0011 §1) y
el append-only real (ADR-0011 §2). Requiere PostgreSQL (`platform_ledger`).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import platform_contracts.events as ev
import pytest
from helpers import lifespan_client
from ledger.config import get_ledger_settings
from ledger.consumer import (
    LedgerEventConsumer,
    client_account_code,
    fund_demo_from_event,
    reset_demo_balance_from_event,
)
from ledger.db import get_session_factory
from ledger.models import LedgerEntry, LedgerTransaction, OutboxEvent
from ledger.pagination import encode_cursor
from ledger.public import encode_period_cursor
from platform_contracts.events import topic_for_event
from platform_kernel.events import build_event
from platform_kernel.security.tokens import new_access_token, new_service_token
from sqlalchemy import func, select, text

pytestmark = pytest.mark.integration

URL = "/internal/v1/postings"
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")

SERVICE_TOKEN = new_service_token(
    service_name="identity",
    secret=os.environ["SERVICE_TOKEN_SECRET"],
    issuer="platform-identity",
    audience="platform-internal",
)
HEADERS = {"Authorization": f"Bearer {SERVICE_TOKEN}"}

OCCURRED = "2026-09-29T12:00:00Z"
CONTROL_ASSET = "1200.RECEIVABLE.PSP.USD"
CLIENT_LIABILITY = "2000.PAYABLE.CLIENT.USD.u1"


@pytest.fixture
async def ledger_client(clean_dbs: None):  # type: ignore[no-untyped-def]
    from ledger.config import get_ledger_settings
    from ledger.db import reset_engine

    # El relay real necesita Redpanda; aquí se verifica la fila del outbox atómica.
    # Se fija SOLO durante este fixture: un volcado global de OUTBOX_RELAY_ENABLED
    # deshabilitaría el relay de identity y romprería la suite e2e (publicación → audit).
    previous = os.environ.get("OUTBOX_RELAY_ENABLED")
    os.environ["OUTBOX_RELAY_ENABLED"] = "false"
    get_ledger_settings.cache_clear()
    reset_engine()

    from ledger.main import create_app

    try:
        async with lifespan_client(create_app()) as client:
            yield client
    finally:
        if previous is None:
            os.environ.pop("OUTBOX_RELAY_ENABLED", None)
        else:
            os.environ["OUTBOX_RELAY_ENABLED"] = previous
        get_ledger_settings.cache_clear()
        reset_engine()


def _access_token(roles: list[str]) -> str:
    return new_access_token(
        user_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        roles=roles,
        secret=os.environ["JWT_SECRET"],
        issuer="platform-identity",
        audience="platform-api",
        ttl_seconds=900,
    )


def _user_token(user_id: uuid.UUID) -> str:
    return new_access_token(
        user_id=str(user_id),
        session_id=str(uuid.uuid4()),
        roles=["user"],
        secret=os.environ["JWT_SECRET"],
        issuer="platform-identity",
        audience="platform-api",
        ttl_seconds=900,
    )


def _range_days(days: int = 1) -> dict[str, str]:
    """Rango `[now-days, now+1d)` para cubrir `created_at = now()` de la BD."""
    now = datetime.now(UTC)
    return {
        "from": (now - timedelta(days=days)).isoformat(),
        "to": (now + timedelta(days=1)).isoformat(),
    }


def _body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "deposit",
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": OCCURRED,
        "metadata": {"source": "test"},
        "entries": [
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": "1000.00", "currency": "USD"},
            {
                "account_code": CLIENT_LIABILITY,
                "direction": "C",
                "amount": "1000.00",
                "currency": "USD",
                "owner_id": str(USER_A),
            },
        ],
    }
    payload.update(overrides)
    return payload


async def _post(client, body: dict[str, Any], key: str | None = None, **kwargs: Any):  # type: ignore[no-untyped-def]
    headers = dict(HEADERS)
    if key is not None:
        headers["Idempotency-Key"] = key
    return await client.post(URL, json=body, headers=headers, **kwargs)


# --------------------------------------------------------------------------- autenticación


async def test_postings_requiere_token_de_servicio(ledger_client) -> None:  # type: ignore[no-untyped-def]
    anonymous = await ledger_client.post(URL, json=_body())
    assert anonymous.status_code == 401

    user = await ledger_client.post(
        URL,
        json=_body(),
        headers={"Authorization": f"Bearer {_access_token(['admin'])}"},
    )
    assert user.status_code == 401


async def test_lectura_requiere_token_de_servicio(ledger_client) -> None:  # type: ignore[no-untyped-def]
    response = await ledger_client.get(f"{URL}/{uuid.uuid4()}")
    assert response.status_code == 401


# --------------------------------------------------------------------------- Idempotency-Key (ADR-0010, Q §1.8)


async def test_idempotency_key_ausente_devuelve_400_de_validacion(ledger_client) -> None:  # type: ignore[no-untyped-def]
    response = await _post(ledger_client, _body())
    assert response.status_code == 400
    problem = response.json()
    assert problem["type"] == "urn:platform:error:validation"
    assert problem["status"] == 400
    assert "Idempotency-Key" in problem["detail"]


async def test_idempotency_key_no_uuid_devuelve_400_de_validacion(ledger_client) -> None:  # type: ignore[no-untyped-def]
    response = await _post(ledger_client, _body(), key="no-es-un-uuid")
    assert response.status_code == 400
    assert response.json()["type"] == "urn:platform:error:validation"


async def test_replay_idempotente_reutiliza_la_transaccion(ledger_client) -> None:  # type: ignore[no-untyped-def]
    key = str(uuid.uuid4())
    body = _body()

    first = await _post(ledger_client, body, key)
    assert first.status_code == 201
    assert first.headers["Idempotent-Replay"] == "false"

    second = await _post(ledger_client, body, key)
    assert second.status_code == 201
    assert second.headers["Idempotent-Replay"] == "true"
    assert second.json() == first.json()

    transaction_id = first.json()["transaction_id"]
    factory = get_session_factory()
    async with factory() as session:
        transactions = await session.scalar(
            select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.id == uuid.UUID(transaction_id))
        )
        events = await session.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == transaction_id)
        )
    assert transactions == 1
    assert events == 1  # invariante 7: 1 transacción ⇒ 1 LedgerPosted


async def test_clave_reutilizada_con_cuerpo_distinto_devuelve_409(ledger_client) -> None:  # type: ignore[no-untyped-def]
    key = str(uuid.uuid4())
    assert (await _post(ledger_client, _body(), key)).status_code == 201

    conflicto = await _post(ledger_client, _body(metadata={"source": "otro"}), key)
    assert conflicto.status_code == 409
    problem = conflicto.json()
    assert problem["type"] == "urn:platform:error:idempotency-key-reuse"
    assert problem["original_created_at"]


# --------------------------------------------------------------------------- invariants de asiento


async def test_posting_valido_devuelve_201_y_es_consultable(ledger_client) -> None:  # type: ignore[no-untyped-def]
    response = await _post(ledger_client, _body(), key=str(uuid.uuid4()))
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "deposit"
    assert [entry["position"] for entry in data["entries"]] == [1, 2]  # invariante 9
    assert [entry["direction"] for entry in data["entries"]] == ["D", "C"]
    assert [entry["amount"] for entry in data["entries"]] == ["1000", "1000"]  # ADR-0006 canónico
    assert data["entries"][0]["account_code"] == CONTROL_ASSET

    found = await ledger_client.get(f"{URL}/{data['transaction_id']}", headers=HEADERS)
    assert found.status_code == 200
    assert found.json()["transaction_id"] == data["transaction_id"]


async def test_posting_inexistente_devuelve_404(ledger_client) -> None:  # type: ignore[no-untyped-def]
    response = await ledger_client.get(f"{URL}/{uuid.uuid4()}", headers=HEADERS)
    assert response.status_code == 404


async def test_posting_desbalanceado_devuelve_422(ledger_client) -> None:  # type: ignore[no-untyped-def]
    body = _body(
        entries=[
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": "1000.00", "currency": "USD"},
            {
                "account_code": CLIENT_LIABILITY,
                "direction": "C",
                "amount": "999.00",
                "currency": "USD",
                "owner_id": str(USER_A),
            },
        ]
    )
    response = await _post(ledger_client, body, key=str(uuid.uuid4()))
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "urn:platform:error:validation"
    assert "desbalanceados" in problem["detail"]


async def test_importe_numerico_devuelve_422(ledger_client) -> None:  # type: ignore[no-untyped-def]
    body = _body(
        entries=[
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": 1000.5, "currency": "USD"},
            {
                "account_code": CLIENT_LIABILITY,
                "direction": "C",
                "amount": "1000.5",
                "currency": "USD",
                "owner_id": str(USER_A),
            },
        ]
    )
    response = await _post(ledger_client, body, key=str(uuid.uuid4()))
    assert response.status_code == 422
    assert response.json()["type"] == "urn:platform:error:validation"


async def test_cuenta_fuera_del_plan_devuelve_422(ledger_client) -> None:  # type: ignore[no-untyped-def]
    body = _body(
        entries=[
            {"account_code": "9999.CRYPTO.USD", "direction": "D", "amount": "1000.00", "currency": "USD"},
            {
                "account_code": CLIENT_LIABILITY,
                "direction": "C",
                "amount": "1000.00",
                "currency": "USD",
                "owner_id": str(USER_A),
            },
        ]
    )
    response = await _post(ledger_client, body, key=str(uuid.uuid4()))
    assert response.status_code == 422
    assert "fuera del plan" in response.json()["detail"]


async def test_cuenta_no_control_sin_owner_devuelve_422(ledger_client) -> None:  # type: ignore[no-untyped-def]
    body = _body(
        entries=[
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": "1000.00", "currency": "USD"},
            {"account_code": CLIENT_LIABILITY, "direction": "C", "amount": "1000.00", "currency": "USD"},
        ]
    )
    response = await _post(ledger_client, body, key=str(uuid.uuid4()))
    assert response.status_code == 422
    assert "requiere owner_id" in response.json()["detail"]


async def test_moneda_mixta_solo_en_conversion(ledger_client) -> None:  # type: ignore[no-untyped-def]
    transferencia = _body(
        type="transfer",
        entries=[
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": "100.00", "currency": "USD"},
            {"account_code": CONTROL_ASSET, "direction": "C", "amount": "100.00", "currency": "EUR"},
        ],
    )
    rechazada = await _post(ledger_client, transferencia, key=str(uuid.uuid4()))
    assert rechazada.status_code == 422
    assert "no admite más de una moneda" in rechazada.json()["detail"]

    conversion = _body(
        type="conversion",
        entries=[
            {
                "account_code": CLIENT_LIABILITY,
                "direction": "D",
                "amount": "928",
                "currency": "USD",
                "owner_id": str(USER_A),
            },
            {
                "account_code": "2000.PAYABLE.CLIENT.EUR.u1",
                "direction": "C",
                "amount": "920",
                "currency": "EUR",
                "owner_id": str(USER_A),
            },
            {"account_code": "4000.REVENUE.FEE.USD", "direction": "C", "amount": "8", "currency": "USD"},
        ],
    )
    aceptada = await _post(ledger_client, conversion, key=str(uuid.uuid4()))
    assert aceptada.status_code == 201


# --------------------------------------------------------------------------- reversión (L §3, invariante 6)


async def test_reversion_simetrica_y_conflicto_por_doble_reversion(ledger_client) -> None:  # type: ignore[no-untyped-def]
    original = await _post(ledger_client, _body(), key=str(uuid.uuid4()))
    assert original.status_code == 201
    tx_id = original.json()["transaction_id"]

    reversion = _body(
        type="reversal",
        reverses_tx_id=tx_id,
        entries=[
            {
                "account_code": CLIENT_LIABILITY,
                "direction": "D",
                "amount": "1000.00",
                "currency": "USD",
                "owner_id": str(USER_A),
            },
            {"account_code": CONTROL_ASSET, "direction": "C", "amount": "1000.00", "currency": "USD"},
        ],
    )
    primera = await _post(ledger_client, reversion, key=str(uuid.uuid4()))
    assert primera.status_code == 201
    assert primera.json()["reverses_tx_id"] == tx_id

    segunda = await _post(ledger_client, reversion, key=str(uuid.uuid4()))
    assert segunda.status_code == 409
    assert segunda.json()["type"] == "urn:platform:error:conflict"


async def test_reverses_tx_id_solo_para_tipo_reversal(ledger_client) -> None:  # type: ignore[no-untyped-def]
    original = await _post(ledger_client, _body(), key=str(uuid.uuid4()))
    assert original.status_code == 201

    malformada = _body(reverses_tx_id=original.json()["transaction_id"])
    response = await _post(ledger_client, malformada, key=str(uuid.uuid4()))
    assert response.status_code == 422
    assert "solo type='reversal' admite" in response.json()["detail"]


# --------------------------------------------------------------------------- outbox atómico (invariante 7)


async def test_transaccion_genera_un_ledger_posted_en_el_outbox(ledger_client) -> None:  # type: ignore[no-untyped-def]
    response = await _post(ledger_client, _body(), key=str(uuid.uuid4()))
    assert response.status_code == 201
    transaction_id = response.json()["transaction_id"]

    factory = get_session_factory()
    async with factory() as session:
        row = (
            (await session.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == transaction_id)))
            .scalars()
            .one()
        )
    assert row.event_type == "LedgerPosted"
    assert row.producer == "ledger"
    assert row.aggregate_type == "LedgerTransaction"
    assert row.schema_version == 1
    assert row.correlation_id == response.json()["correlation_id"]
    assert row.payload["transaction_id"] == transaction_id
    assert [entry["amount"] for entry in row.payload["entries"]] == ["1000", "1000"]
    assert row.published_at is None
    assert row.publish_attempts == 0

    from ledger.outbox import encode_envelope

    envelope = json.loads(encode_envelope(row))
    assert envelope["event_id"] == row.id
    assert envelope["event_type"] == "LedgerPosted"
    assert envelope["producer"] == "ledger"

    assert topic_for_event("ledger", "LedgerTransaction", "LedgerPosted") == "ledger.ledger_transaction.ledger_posted"


# --------------------------------------------------------------------------- inmutabilidad (ADR-0011 §1/§2)


async def test_asientos_y_transacciones_son_append_only(ledger_client) -> None:  # type: ignore[no-untyped-def]
    response = await _post(ledger_client, _body(), key=str(uuid.uuid4()))
    assert response.status_code == 201
    transaction_id = uuid.UUID(response.json()["transaction_id"])

    factory = get_session_factory()
    async with factory() as session:
        entry = (
            (
                await session.execute(
                    select(LedgerEntry).where(
                        LedgerEntry.transaction_id == transaction_id,
                        LedgerEntry.position == 1,
                    )
                )
            )
            .scalars()
            .one()
        )
        entry.amount = Decimal("1.000000000000000000")
        with pytest.raises(RuntimeError, match="append-only"):
            await session.flush()
        await session.rollback()

    async with factory() as session:
        entry = (
            (
                await session.execute(
                    select(LedgerEntry).where(
                        LedgerEntry.transaction_id == transaction_id,
                        LedgerEntry.position == 1,
                    )
                )
            )
            .scalars()
            .one()
        )
        await session.delete(entry)
        with pytest.raises(RuntimeError, match="append-only"):
            await session.flush()
        await session.rollback()

    async with factory() as session:
        transaction = (
            (await session.execute(select(LedgerTransaction).where(LedgerTransaction.id == transaction_id)))
            .scalars()
            .one()
        )
        transaction.type = "adjustment"
        with pytest.raises(RuntimeError, match="append-only"):
            await session.flush()
        await session.rollback()


async def test_trigger_de_postgres_bloquea_update_y_delete(ledger_client) -> None:  # type: ignore[no-untyped-def]
    response = await _post(ledger_client, _body(), key=str(uuid.uuid4()))
    assert response.status_code == 201
    transaction_id = response.json()["transaction_id"]

    factory = get_session_factory()
    async with factory() as session:
        with pytest.raises(Exception, match="append-only"):
            await session.execute(
                text("UPDATE ledger.ledger_entries SET amount = amount WHERE transaction_id = CAST(:tx AS uuid)"),
                {"tx": transaction_id},
            )
        await session.rollback()

    async with factory() as session:
        with pytest.raises(Exception, match="append-only"):
            await session.execute(
                text("DELETE FROM ledger.ledger_transactions WHERE id = CAST(:tx AS uuid)"),
                {"tx": transaction_id},
            )
        await session.rollback()


async def test_funcion_de_balance_rechaza_asiento_desbalanceado(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """ADR-0011 §1: `ledger.ledger_assert_balanced` es la defensa en profundidad."""
    response = await _post(ledger_client, _body(), key=str(uuid.uuid4()))
    assert response.status_code == 201
    transaction_id = response.json()["transaction_id"]
    entry_id = response.json()["entries"][0]["entry_id"]

    factory = get_session_factory()
    async with factory() as session:
        with pytest.raises(Exception, match="not balanced"):
            await session.execute(
                text(
                    "INSERT INTO ledger.ledger_entries "
                    "(id, transaction_id, account_id, direction, amount, currency, position, created_at) "
                    "SELECT CAST(:extra AS uuid), transaction_id, account_id, 'D', 1.0, currency, 99, now() "
                    "FROM ledger.ledger_entries WHERE id = CAST(:entry AS uuid)"
                ),
                {"extra": str(uuid.uuid4()), "entry": entry_id},
            )
            await session.execute(
                text("SELECT ledger.ledger_assert_balanced(CAST(:tx AS uuid))"), {"tx": transaction_id}
            )
        await session.rollback()


async def test_cuentas_se_autocrean_y_quedan_consistentes(ledger_client) -> None:  # type: ignore[no-untyped-def]
    response = await _post(ledger_client, _body(), key=str(uuid.uuid4()))
    assert response.status_code == 201

    factory = get_session_factory()
    async with factory() as session:
        codes = (
            await session.execute(text("SELECT code, type, is_control FROM ledger.ledger_accounts ORDER BY code"))
        ).all()
    by_code = {code: (type_, control) for code, type_, control in codes}
    assert by_code[CONTROL_ASSET] == ("asset", True)
    assert by_code[CLIENT_LIABILITY] == ("liability", False)

    # reutilizar la misma cuenta con otro owner debe fallar (L §7.1)
    cuerpo = _body(
        entries=[
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": "10.00", "currency": "USD"},
            {
                "account_code": CLIENT_LIABILITY,
                "direction": "C",
                "amount": "10.00",
                "currency": "USD",
                "owner_id": str(uuid.uuid4()),
            },
        ]
    )
    conflicto = await _post(ledger_client, cuerpo, key=str(uuid.uuid4()))
    assert conflicto.status_code == 422
    assert "pertenece a otro owner_id" in conflicto.json()["detail"]


# --------------------------------------------------------------------------- sistema


async def test_healthz_y_readyz(ledger_client) -> None:  # type: ignore[no-untyped-def]
    health = await ledger_client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"service": "ledger", "status": "ok"}

    ready = await ledger_client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


async def test_metrica_de_postings_se_incrementa(ledger_client) -> None:  # type: ignore[no-untyped-def]
    from prometheus_client import REGISTRY

    before = REGISTRY.get_sample_value("platform_ledger_postings_total", {"type": "deposit"}) or 0.0

    response = await _post(ledger_client, _body(), key=str(uuid.uuid4()))
    assert response.status_code == 201

    after = REGISTRY.get_sample_value("platform_ledger_postings_total", {"type": "deposit"})
    assert after is not None and after > before


# ----------------------------------------------------------------- balances internos (Q §3, F2.3)


async def test_balances_internos_requiere_token_de_servicio(ledger_client) -> None:  # type: ignore[no-untyped-def]
    anonimo = await ledger_client.get("/internal/v1/balances")
    assert anonimo.status_code == 401

    usuario = await ledger_client.get(
        "/internal/v1/balances",
        headers={"Authorization": f"Bearer {_access_token(['user'])}"},
    )
    assert usuario.status_code == 401

    ok = await ledger_client.get("/internal/v1/balances", headers=HEADERS)
    assert ok.status_code == 200
    body = ok.json()
    assert isinstance(body["data"], list)
    assert body["as_of"]


async def test_balances_internos_refleja_postings(ledger_client) -> None:  # type: ignore[no-untyped-def]
    owner = uuid.uuid4()
    body = _body(
        entries=[
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": "250.50", "currency": "USD"},
            {
                "account_code": client_account_code("USD", owner),
                "direction": "C",
                "amount": "250.50",
                "currency": "USD",
                "owner_id": str(owner),
            },
        ]
    )
    response = await _post(ledger_client, body, key=str(uuid.uuid4()))
    assert response.status_code == 201

    filtrado = await ledger_client.get(
        "/internal/v1/balances",
        params={"owner_id": str(owner)},
        headers=HEADERS,
    )
    assert filtrado.status_code == 200
    # sólo cuentas no control (L §4.1): la de control queda fuera
    assert filtrado.json()["data"] == [{"owner_id": str(owner), "currency": "USD", "balance": "250.5"}]

    todos = await ledger_client.get("/internal/v1/balances", headers=HEADERS)
    assert any(row["owner_id"] == str(owner) and row["balance"] == "250.5" for row in todos.json()["data"])


# ----------------------------------------------------------------- consumidor demo #16/#17 (F2.3)


def _demo_envelope(event_type: str, payload: dict[str, Any]) -> Any:  # type: ignore[no-untyped-def]
    return build_event(
        event_type=event_type,
        schema_version=ev.EVENT_TYPES_PHASE2[event_type],
        aggregate_id=str(uuid.uuid4()),
        aggregate_type=ev.EVENT_AGGREGATE_TYPE[event_type],
        producer="accounts",
        payload=payload,
    )


async def test_consumidor_fondea_demo_idempotente(ledger_client) -> None:  # type: ignore[no-untyped-def]
    settings = get_ledger_settings()
    user_id = uuid.uuid4()
    envelope = _demo_envelope(
        ev.DEMO_ACCOUNT_CREATED,
        {"user_id": str(user_id), "currency": "USD", "initial_balance": "10000"},
    )

    factory = get_session_factory()
    async with factory() as session:
        assert await fund_demo_from_event(session, settings, envelope) is True
    # reentrega at-least-once: la idempotencia (ADR-0010) evita el doble fondeo
    async with factory() as session:
        assert await fund_demo_from_event(session, settings, envelope) is False

    balances = await ledger_client.get(
        "/internal/v1/balances",
        params={"owner_id": str(user_id)},
        headers=HEADERS,
    )
    assert balances.json()["data"] == [{"owner_id": str(user_id), "currency": "USD", "balance": "10000"}]

    # payload inválido y balance no positivo → False (sin romper el consumer)
    invalido = _demo_envelope(ev.DEMO_ACCOUNT_CREATED, {"currency": "USD"})
    async with factory() as session:
        assert await fund_demo_from_event(session, settings, invalido) is False
    no_positivo = _demo_envelope(
        ev.DEMO_ACCOUNT_CREATED,
        {"user_id": str(uuid.uuid4()), "currency": "USD", "initial_balance": "0"},
    )
    async with factory() as session:
        assert await fund_demo_from_event(session, settings, no_positivo) is False


async def test_consumidor_reinicia_saldo_con_delta(ledger_client) -> None:  # type: ignore[no-untyped-def]
    settings = get_ledger_settings()
    user_id = uuid.uuid4()
    factory = get_session_factory()

    fund = _demo_envelope(
        ev.DEMO_ACCOUNT_CREATED,
        {"user_id": str(user_id), "currency": "USD", "initial_balance": "10000"},
    )
    async with factory() as session:
        assert await fund_demo_from_event(session, settings, fund) is True

    reset = _demo_envelope(
        ev.DEMO_BALANCE_RESET,
        {"user_id": str(user_id), "currency": "USD", "new_balance": "7500"},
    )
    async with factory() as session:
        assert await reset_demo_balance_from_event(session, settings, reset) is True
    # misma reentrega → idempotente
    async with factory() as session:
        assert await reset_demo_balance_from_event(session, settings, reset) is False

    balances = await ledger_client.get(
        "/internal/v1/balances",
        params={"owner_id": str(user_id)},
        headers=HEADERS,
    )
    assert balances.json()["data"][0]["balance"] == "7500"

    # sin delta (otro event_id con el mismo objetivo) → False, sin asiento
    sin_delta = _demo_envelope(
        ev.DEMO_BALANCE_RESET,
        {"user_id": str(user_id), "currency": "USD", "new_balance": "7500"},
    )
    async with factory() as session:
        assert await reset_demo_balance_from_event(session, settings, sin_delta) is False

    # delta positivo (subida de saldo de la demo)
    subida = _demo_envelope(
        ev.DEMO_BALANCE_RESET,
        {"user_id": str(user_id), "currency": "USD", "new_balance": "12000"},
    )
    async with factory() as session:
        assert await reset_demo_balance_from_event(session, settings, subida) is True
    balances = await ledger_client.get(
        "/internal/v1/balances",
        params={"owner_id": str(user_id)},
        headers=HEADERS,
    )
    assert balances.json()["data"][0]["balance"] == "12000"

    # payload inválido y saldo negativo → False
    invalido = _demo_envelope(ev.DEMO_BALANCE_RESET, {"user_id": str(user_id)})
    async with factory() as session:
        assert await reset_demo_balance_from_event(session, settings, invalido) is False
    negativo = _demo_envelope(
        ev.DEMO_BALANCE_RESET,
        {"user_id": str(user_id), "currency": "USD", "new_balance": "-1"},
    )
    async with factory() as session:
        assert await reset_demo_balance_from_event(session, settings, negativo) is False


async def test_reinicio_sin_fondeo_previo_y_en_moneda_distinta(ledger_client) -> None:  # type: ignore[no-untyped-def]
    settings = get_ledger_settings()
    factory = get_session_factory()

    # owner sin cuentas: `_owner_balance` no itera ninguna fila y devuelve 0
    fresco = uuid.uuid4()
    reset = _demo_envelope(
        ev.DEMO_BALANCE_RESET,
        {"user_id": str(fresco), "currency": "USD", "new_balance": "500"},
    )
    async with factory() as session:
        assert await reset_demo_balance_from_event(session, settings, reset) is True
    balances = await ledger_client.get("/internal/v1/balances", params={"owner_id": str(fresco)}, headers=HEADERS)
    assert balances.json()["data"] == [{"owner_id": str(fresco), "currency": "USD", "balance": "500"}]

    # fondeo en EUR y reinicio en USD: el owner existe pero en otra moneda
    otro = uuid.uuid4()
    fund = _demo_envelope(
        ev.DEMO_ACCOUNT_CREATED,
        {"user_id": str(otro), "currency": "EUR", "initial_balance": "100"},
    )
    async with factory() as session:
        assert await fund_demo_from_event(session, settings, fund) is True
    reset_usd = _demo_envelope(
        ev.DEMO_BALANCE_RESET,
        {"user_id": str(otro), "currency": "USD", "new_balance": "250"},
    )
    async with factory() as session:
        assert await reset_demo_balance_from_event(session, settings, reset_usd) is True
    balances = await ledger_client.get("/internal/v1/balances", params={"owner_id": str(otro)}, headers=HEADERS)
    assert {row["currency"]: row["balance"] for row in balances.json()["data"]} == {"EUR": "100", "USD": "250"}


async def test_consumidor_rechaza_cuentas_inconsistentes(ledger_client) -> None:  # type: ignore[no-untyped-def]
    settings = get_ledger_settings()
    factory = get_session_factory()
    user_id = uuid.uuid4()

    # la cuenta de cliente de este usuario existe con un owner_id distinto
    # (códigos por usuario: el envenenamiento no afecta al resto de la suite)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO ledger.ledger_accounts "
                "(id, code, name, type, currency, owner_id, owner_type, is_control, created_at) "
                "VALUES (:id, :code, 'cliente', 'liability', 'USD', :owner, 'user', false, now())"
            ),
            {"id": uuid.uuid4(), "code": client_account_code("USD", user_id), "owner": uuid.uuid4()},
        )
        await session.commit()

    fund = _demo_envelope(
        ev.DEMO_ACCOUNT_CREATED,
        {"user_id": str(user_id), "currency": "USD", "initial_balance": "10000"},
    )
    async with factory() as session:
        assert await fund_demo_from_event(session, settings, fund) is False

    reset = _demo_envelope(
        ev.DEMO_BALANCE_RESET,
        {"user_id": str(user_id), "currency": "USD", "new_balance": "7500"},
    )
    async with factory() as session:
        assert await reset_demo_balance_from_event(session, settings, reset) is False

    balances = await ledger_client.get("/internal/v1/balances", params={"owner_id": str(user_id)}, headers=HEADERS)
    assert balances.json()["data"] == []


class _ConsumidorFalso:
    """Doble de `AIOKafkaConsumer` que sólo registra los `commit`."""

    def __init__(self) -> None:
        self.commits: list[Any] = []

    async def commit(self, offsets: Any) -> None:
        self.commits.append(offsets)


def _mensaje(envelope: Any, offset: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        topic="accounts.trading_account.demo",
        partition=0,
        offset=offset,
        value=json.dumps(envelope.model_dump(mode="json")).encode(),
    )


async def test_consumidor_handle_descarta_mensaje_invalido(ledger_client) -> None:  # type: ignore[no-untyped-def]
    consumer = LedgerEventConsumer(get_session_factory(), get_ledger_settings())
    fake = _ConsumidorFalso()
    await consumer._handle(fake, SimpleNamespace(topic="t", partition=0, offset=4, value=b"no es json"))
    assert len(fake.commits) == 1
    assert list(fake.commits[0].values()) == [5]


async def test_consumidor_handle_fondea_y_omite_replay(ledger_client) -> None:  # type: ignore[no-untyped-def]
    consumer = LedgerEventConsumer(get_session_factory(), get_ledger_settings())
    user_id = uuid.uuid4()
    envelope = _demo_envelope(
        ev.DEMO_ACCOUNT_CREATED,
        {"user_id": str(user_id), "currency": "USD", "initial_balance": "10000"},
    )
    fake = _ConsumidorFalso()
    await consumer._handle(fake, _mensaje(envelope, offset=10))
    await consumer._handle(fake, _mensaje(envelope, offset=11))
    assert len(fake.commits) == 2

    balances = await ledger_client.get("/internal/v1/balances", params={"owner_id": str(user_id)}, headers=HEADERS)
    assert balances.json()["data"][0]["balance"] == "10000"


async def test_consumidor_handle_reinicia_y_omite_sin_delta(ledger_client) -> None:  # type: ignore[no-untyped-def]
    settings = get_ledger_settings()
    factory = get_session_factory()
    user_id = uuid.uuid4()
    fund = _demo_envelope(
        ev.DEMO_ACCOUNT_CREATED,
        {"user_id": str(user_id), "currency": "USD", "initial_balance": "10000"},
    )
    async with factory() as session:
        assert await fund_demo_from_event(session, settings, fund) is True

    consumer = LedgerEventConsumer(factory, settings)
    fake = _ConsumidorFalso()
    reset = _demo_envelope(
        ev.DEMO_BALANCE_RESET,
        {"user_id": str(user_id), "currency": "USD", "new_balance": "7500"},
    )
    sin_delta = _demo_envelope(
        ev.DEMO_BALANCE_RESET,
        {"user_id": str(user_id), "currency": "USD", "new_balance": "7500"},
    )
    await consumer._handle(fake, _mensaje(reset, offset=20))
    await consumer._handle(fake, _mensaje(sin_delta, offset=21))
    assert len(fake.commits) == 2

    balances = await ledger_client.get("/internal/v1/balances", params={"owner_id": str(user_id)}, headers=HEADERS)
    assert balances.json()["data"][0]["balance"] == "7500"


async def test_consumidor_handle_omite_tipo_no_implementado(ledger_client) -> None:  # type: ignore[no-untyped-def]
    consumer = LedgerEventConsumer(get_session_factory(), get_ledger_settings())
    envelope = build_event(
        event_type=ev.LEDGER_POSTED,
        schema_version=1,
        aggregate_id=str(uuid.uuid4()),
        aggregate_type="LedgerTransaction",
        producer="ledger",
        payload={},
    )
    fake = _ConsumidorFalso()
    await consumer._handle(fake, _mensaje(envelope, offset=30))
    assert len(fake.commits) == 1


async def test_consumidor_run_reintenta_tras_fallo(ledger_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    consumer = LedgerEventConsumer(get_session_factory(), get_ledger_settings())
    calls = 0

    async def _fallo() -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            consumer._stopped.set()
        raise RuntimeError("redpanda no disponible")

    monkeypatch.setattr(consumer, "_consume", _fallo)
    monkeypatch.setattr("ledger.consumer.RETRY_DELAY_SECONDS", 0.05)
    await consumer.start()
    assert await asyncio.wait_for(consumer._task, timeout=5) is None
    assert calls >= 2
    await consumer.stop()


async def test_consumidor_stop_y_consume_con_doble_de_kafka(ledger_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    registros = [SimpleNamespace(topic="t", partition=0, offset=0, value=b"no es json")]
    commits: list[Any] = []
    consumer = LedgerEventConsumer(get_session_factory(), get_ledger_settings())

    class _FalsoKafka(_ConsumidorFalso):
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            super().__init__()
            self._peticiones = 0

        async def start(self) -> None:
            pass

        async def getone(self) -> Any:
            if self._peticiones < len(registros):
                registro = registros[self._peticiones]
                self._peticiones += 1
                return registro
            consumer._stopped.set()
            return registros[0]

        async def commit(self, offsets: Any) -> None:
            commits.append(offsets)
            await super().commit(offsets)

        async def stop(self) -> None:
            pass

    monkeypatch.setattr("ledger.consumer.AIOKafkaConsumer", _FalsoKafka)

    # stop() sin start(): rama falsa de `if self._task`
    await consumer.stop()
    assert consumer._task is None

    # con la bandera limpiada, `_consume` procesa un mensaje y sale al volver la bandera
    consumer._stopped.clear()
    await consumer._consume()
    assert len(commits) == 2
    assert consumer._consumer is None


# ------------------------------------------------------------------------ API pública (Q §2.6, F2.3)


async def test_public_entries_exige_sesion_y_rango(ledger_client) -> None:  # type: ignore[no-untyped-def]
    anonimo = await ledger_client.get("/api/v1/ledger/entries", params=_range_days())
    assert anonimo.status_code == 401

    token = _user_token(uuid.uuid4())
    headers = {"Authorization": f"Bearer {token}"}
    sin_rango = await ledger_client.get("/api/v1/ledger/entries", headers=headers)
    assert sin_rango.status_code == 422

    invertido = await ledger_client.get(
        "/api/v1/ledger/entries", params={"from": "2026-09-02T00:00:00Z", "to": "2026-09-01T00:00:00Z"}, headers=headers
    )
    assert invertido.status_code == 422

    excesivo = await ledger_client.get(
        "/api/v1/ledger/entries",
        params={"from": "2020-01-01T00:00:00Z", "to": "2026-12-01T00:00:00Z"},
        headers=headers,
    )
    assert excesivo.status_code == 422
    assert "90" in excesivo.json()["detail"]


async def test_public_entries_lista_asientos_propios_y_bola(ledger_client) -> None:  # type: ignore[no-untyped-def]
    owner = uuid.uuid4()
    other = uuid.uuid4()

    def _deposit(account_owner: uuid.UUID, amount: str) -> dict[str, Any]:
        return _body(
            entries=[
                {"account_code": CONTROL_ASSET, "direction": "D", "amount": amount, "currency": "USD"},
                {
                    "account_code": client_account_code("USD", account_owner),
                    "direction": "C",
                    "amount": amount,
                    "currency": "USD",
                    "owner_id": str(account_owner),
                },
            ]
        )

    propio = await _post(ledger_client, _deposit(owner, "1000.00"), key=str(uuid.uuid4()))
    assert propio.status_code == 201
    ajeno = await _post(ledger_client, _deposit(other, "500.00"), key=str(uuid.uuid4()))
    assert ajeno.status_code == 201
    cuenta_propia = next(e["account_id"] for e in propio.json()["entries"] if e["direction"] == "C")
    cuenta_ajena = next(e["account_id"] for e in ajeno.json()["entries"] if e["direction"] == "C")

    headers = {"Authorization": f"Bearer {_user_token(owner)}"}
    response = await ledger_client.get("/api/v1/ledger/entries", params=_range_days(), headers=headers)
    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows, "el owner debe ver sus propios asientos"
    assert {row["amount"] for row in rows} == {"1000"}
    assert all(row["account_code"] == client_account_code("USD", owner) for row in rows)

    # BOLA §1.7.3: cuenta ajena, inexistente o de otro usuario → 404 idéntico
    ajena_filtro = await ledger_client.get(
        "/api/v1/ledger/entries",
        params={**_range_days(), "account_id": cuenta_ajena},
        headers=headers,
    )
    assert ajena_filtro.status_code == 404

    inexistente = await ledger_client.get(
        "/api/v1/ledger/entries",
        params={**_range_days(), "account_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert inexistente.status_code == 404
    # misma respuesta tipada (S §1.7.3): sólo difieren los ids de correlación de cada request
    assert {k: v for k, v in inexistente.json().items() if k not in ("correlation_id", "request_id")} == {
        k: v for k, v in ajena_filtro.json().items() if k not in ("correlation_id", "request_id")
    }

    ajeno_token = await ledger_client.get(
        "/api/v1/ledger/entries",
        params={**_range_days(), "account_id": cuenta_propia},
        headers={"Authorization": f"Bearer {_user_token(uuid.uuid4())}"},
    )
    assert ajeno_token.status_code == 404

    # filtro por cuenta propia: devuelve exactamente sus asientos
    propio_filtro = await ledger_client.get(
        "/api/v1/ledger/entries",
        params={**_range_days(), "account_id": cuenta_propia},
        headers=headers,
    )
    assert propio_filtro.status_code == 200
    assert {row["amount"] for row in propio_filtro.json()["data"]} == {"1000"}


async def test_public_entries_cursor_sin_duplicados(ledger_client) -> None:  # type: ignore[no-untyped-def]
    owner = uuid.uuid4()
    for _ in range(2):
        body = _body(
            entries=[
                {"account_code": CONTROL_ASSET, "direction": "D", "amount": "10.00", "currency": "USD"},
                {
                    "account_code": client_account_code("USD", owner),
                    "direction": "C",
                    "amount": "10.00",
                    "currency": "USD",
                    "owner_id": str(owner),
                },
            ]
        )
        assert (await _post(ledger_client, body, key=str(uuid.uuid4()))).status_code == 201

    headers = {"Authorization": f"Bearer {_user_token(owner)}"}
    page1 = await ledger_client.get("/api/v1/ledger/entries", params={**_range_days(), "limit": 1}, headers=headers)
    assert page1.status_code == 200
    assert page1.json()["page"]["has_more"] is True
    cursor = page1.json()["page"]["next_cursor"]
    assert cursor

    page2 = await ledger_client.get(
        "/api/v1/ledger/entries", params={**_range_days(), "limit": 1, "cursor": cursor}, headers=headers
    )
    assert page2.status_code == 200
    assert page2.json()["page"]["has_more"] is False
    ids1 = {row["entry_id"] for row in page1.json()["data"]}
    ids2 = {row["entry_id"] for row in page2.json()["data"]}
    assert ids1 and ids2 and not (ids1 & ids2)


async def test_public_statements_resumen_y_detalle(ledger_client) -> None:  # type: ignore[no-untyped-def]
    owner = uuid.uuid4()
    body = _body(
        entries=[
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": "300.00", "currency": "USD"},
            {
                "account_code": client_account_code("USD", owner),
                "direction": "C",
                "amount": "300.00",
                "currency": "USD",
                "owner_id": str(owner),
            },
        ]
    )
    assert (await _post(ledger_client, body, key=str(uuid.uuid4()))).status_code == 201
    headers = {"Authorization": f"Bearer {_user_token(owner)}"}

    listing = await ledger_client.get("/api/v1/ledger/statements", headers=headers)
    assert listing.status_code == 200
    items = listing.json()["data"]
    assert len(items) == 1
    statement_id = items[0]["statement_id"]
    assert statement_id == f"{datetime.now(UTC):%Y-%m}-USD"
    assert items[0]["opening_balance"] == "0"
    assert items[0]["closing_balance"] == "300"
    assert items[0]["entries_count"] == 1

    # filtro por moneda
    otras = await ledger_client.get("/api/v1/ledger/statements", params={"currency": "EUR"}, headers=headers)
    assert otras.json()["data"] == []

    detail = await ledger_client.get(f"/api/v1/ledger/statements/{statement_id}", headers=headers)
    assert detail.status_code == 200
    body_detail = detail.json()
    assert body_detail["opening_balance"] == "0"
    assert body_detail["closing_balance"] == "300"
    assert body_detail["entries_count"] == 1
    assert len(body_detail["entries"]) == 1
    assert body_detail["entries"][0]["amount"] == "300"
    assert body_detail["as_of"]

    mal_formado = await ledger_client.get("/api/v1/ledger/statements/XX-USD", headers=headers)
    assert mal_formado.status_code == 422

    desconocido = await ledger_client.get("/api/v1/ledger/statements/2019-01-USD", headers=headers)
    assert desconocido.status_code == 404

    # BOLA: otro usuario no ve el extracto ni el detalle
    ajeno_headers = {"Authorization": f"Bearer {_user_token(uuid.uuid4())}"}
    ajeno_list = await ledger_client.get("/api/v1/ledger/statements", headers=ajeno_headers)
    assert ajeno_list.json()["data"] == []
    ajeno_detail = await ledger_client.get(f"/api/v1/ledger/statements/{statement_id}", headers=ajeno_headers)
    assert ajeno_detail.status_code == 404


async def test_public_statements_cursor_y_detalle_paginado(ledger_client) -> None:  # type: ignore[no-untyped-def]
    owner = uuid.uuid4()
    for currency, amount in (("USD", "100.00"), ("EUR", "50.00"), ("GBP", "25.00")):
        body = _body(
            entries=[
                {
                    "account_code": f"1200.RECEIVABLE.PSP.{currency}",
                    "direction": "D",
                    "amount": amount,
                    "currency": currency,
                },
                {
                    "account_code": f"2000.PAYABLE.CLIENT.{currency}.u_{owner.hex}",
                    "direction": "C",
                    "amount": amount,
                    "currency": currency,
                    "owner_id": str(owner),
                },
            ]
        )
        assert (await _post(ledger_client, body, key=str(uuid.uuid4()))).status_code == 201
    headers = {"Authorization": f"Bearer {_user_token(owner)}"}

    # con `has_more`, `next_cursor` codifica (mes, moneda) — encode_period_cursor
    page1 = await ledger_client.get("/api/v1/ledger/statements", params={"limit": 1}, headers=headers)
    assert page1.status_code == 200
    assert page1.json()["page"]["has_more"] is True
    assert page1.json()["page"]["next_cursor"]

    completo = await ledger_client.get("/api/v1/ledger/statements", headers=headers)
    items = completo.json()["data"]
    assert len(items) == 3
    medio = items[1]
    cursor = encode_period_cursor(datetime.fromisoformat(medio["period"]["from"]), medio["currency"])

    # cursor válido: la primera fila no coincide, el bucle avanza y pagina desde la siguiente
    pagina = await ledger_client.get("/api/v1/ledger/statements", params={"cursor": cursor}, headers=headers)
    assert pagina.status_code == 200
    assert [row["statement_id"] for row in pagina.json()["data"]] == [items[2]["statement_id"]]
    assert pagina.json()["page"]["has_more"] is False

    # cursor válido sin coincidencia → 422 (rama `else` del bucle)
    sin_coincidencia = await ledger_client.get(
        "/api/v1/ledger/statements",
        params={"cursor": encode_period_cursor(datetime(2020, 1, 1, tzinfo=UTC), "JPY")},
        headers=headers,
    )
    assert sin_coincidencia.status_code == 422

    # cursor corrupto → el decode falla → mismo 422 tipado
    corrupto = await ledger_client.get("/api/v1/ledger/statements", params={"cursor": "!!!"}, headers=headers)
    assert corrupto.status_code == 422

    # detalle con cursor: el filtro de entradas usa (created_at, id)
    detalle = await ledger_client.get(
        f"/api/v1/ledger/statements/{items[0]['statement_id']}",
        params={"cursor": encode_cursor(datetime.now(UTC), uuid.uuid4())},
        headers=headers,
    )
    assert detalle.status_code == 200
