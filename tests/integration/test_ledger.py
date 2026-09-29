"""Pruebas de integración del Ledger Service.

Cubre escritura interna idempotente, invariantes 1/4/5/6/7/9/10 de
`L-ledger-architecture.md` §8, la defensa en profundidad en BD (ADR-0011 §1) y
el append-only real (ADR-0011 §2). Requiere PostgreSQL (`platform_ledger`).
"""

from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal
from typing import Any

import pytest
from helpers import lifespan_client
from ledger.db import get_session_factory
from ledger.models import LedgerEntry, LedgerTransaction, OutboxEvent
from platform_contracts.events import topic_for_event
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
