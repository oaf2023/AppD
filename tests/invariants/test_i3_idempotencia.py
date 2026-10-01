"""I3 — Sin ejecuciones duplicadas (ADR-0018 §1, R-002, ADR-0010/0016).

- Replay de 100x de la misma `Idempotency-Key` con el mismo payload ⇒ 1 transacción.
- Misma clave con payload distinto ⇒ 409 `idempotency-key-reuse`.
- Doble POST **concurrente** con la misma clave ⇒ 1 registro efectivo
  (advisory lock + PK de `ledger_idempotency_keys`; ADR-0010 §2).
- Consumidor con evento re-entregado ⇒ 1 efecto (deduplicación en wallet;
  el test canónico con evento real del outbox vive en
  `tests/integration/test_wallet.py::test_ledger_posted_es_deduplicado_por_event_id`
  y aquí se verifica contra el outbox del ledger de esta misma ejecución).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import hypothesis.strategies as st
import pytest
from hypothesis import given
from platform_kernel.events import EventEnvelope
from platform_kernel.security.tokens import new_service_token
from sqlalchemy import func, select

pytestmark = pytest.mark.invariants

URL = "/internal/v1/postings"
OCCURRED = "2026-09-29T12:00:00Z"
CONTROL_ASSET = "1200.RECEIVABLE.PSP.USD"

SERVICE_TOKEN = new_service_token(
    service_name="identity",
    secret=os.environ["SERVICE_TOKEN_SECRET"],
    issuer="platform-identity",
    audience="platform-internal",
)
HEADERS = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


def _body(owner: uuid.UUID, *, metadata: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "type": "deposit",
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": OCCURRED,
        "metadata": metadata or {"source": "invariants-i3"},
        "entries": [
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": "100.00", "currency": "USD"},
            {
                "account_code": f"2000.PAYABLE.CLIENT.USD.u_{owner.hex}",
                "direction": "C",
                "amount": "100.00",
                "currency": "USD",
                "owner_id": str(owner),
            },
        ],
    }


async def _post(client, body: dict[str, object], key: str):  # type: ignore[no-untyped-def]
    return await client.post(URL, json=body, headers={**HEADERS, "Idempotency-Key": key})


# --------------------------------------------------------------------------- replay 100x


async def test_i3_replay_100veces_produce_una_sola_transaccion(ledger_client) -> None:  # type: ignore[no-untyped-def]
    key = str(uuid.uuid4())
    body = _body(uuid.uuid4())

    first = await _post(ledger_client, body, key)
    assert first.status_code == 201
    assert first.headers["Idempotent-Replay"] == "false"
    for _ in range(99):
        replay = await _post(ledger_client, body, key)
        assert replay.status_code == 201
        assert replay.headers["Idempotent-Replay"] == "true"
        assert replay.json() == first.json()

    from ledger.db import get_session_factory
    from ledger.models import LedgerIdempotencyKey, LedgerTransaction, OutboxEvent

    transaction_id = first.json()["transaction_id"]
    factory = get_session_factory()
    async with factory() as session:
        transactions = await session.scalar(
            select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.id == uuid.UUID(transaction_id))
        )
        events = await session.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == transaction_id)
        )
        keys = await session.scalar(
            select(func.count()).select_from(LedgerIdempotencyKey).where(LedgerIdempotencyKey.idempotency_key == key)
        )
    assert transactions == 1
    assert events == 1  # invariante 7: 1 transacción ⇒ exactamente 1 LedgerPosted
    assert keys == 1


# --------------------------------------------------------------------------- payload distinto


@given(mutated=st.sampled_from(["metadata", "amount", "correlation"]))
async def test_i3_clave_reutilizada_con_payload_distinto_devuelve_409(  # type: ignore[no-untyped-def]
    ledger_client, mutated: str
) -> None:
    key = str(uuid.uuid4())
    owner = uuid.uuid4()
    original = _body(owner)
    first = await _post(ledger_client, original, key)
    assert first.status_code == 201
    original_transaction_id = first.json()["transaction_id"]

    conflict = dict(original)
    if mutated == "metadata":
        conflict["metadata"] = {"source": "mutado"}
    elif mutated == "amount":
        # Ambos asientos para que el posting siga balanceado y el 409 no lo tape un 422.
        conflict["entries"] = [{**entry, "amount": "999.00"} for entry in original["entries"]]  # type: ignore[call-overload]
    else:
        conflict["correlation_id"] = str(uuid.uuid4())

    response = await _post(ledger_client, conflict, key)
    assert response.status_code == 409
    problem = response.json()
    assert problem["type"] == "urn:platform:error:idempotency-key-reuse"
    assert problem["original_created_at"]

    # La transacción original quedó intacta: la clave sigue apuntando a ella.
    from ledger.db import get_session_factory
    from ledger.models import LedgerIdempotencyKey

    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(select(LedgerIdempotencyKey).where(LedgerIdempotencyKey.idempotency_key == key))
        ).scalar_one()
        assert str(row.transaction_id) == original_transaction_id


# --------------------------------------------------------------------------- concurrencia


async def test_i3_post_concurrente_misma_clave_produce_una_sola_transaccion(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """Dos POST simultáneos con la misma Idempotency-Key ⇒ exactamente 1 transacción.

    Escenarios admitidos (ADR-0010 §2): (201, 201-replay) si el segundo llega
    tras el COMMIT, o (201, 409-idempotency-in-progress) si el advisory lock
    detecta la reclamación en curso. Ambos dejan 1 fila efectiva.
    """
    key = str(uuid.uuid4())
    body = _body(uuid.uuid4())

    first, second = await asyncio.gather(_post(ledger_client, body, key), _post(ledger_client, body, key))
    statuses = sorted([first.status_code, second.status_code])
    assert statuses in ([201, 201], [201, 409]), statuses
    for response in (first, second):
        if response.status_code == 409:
            assert response.json()["type"] == "urn:platform:error:idempotency-in-progress"
        else:
            assert response.json()["type"] == "deposit"

    winners = [r for r in (first, second) if r.status_code == 201]
    transaction_id = winners[0].json()["transaction_id"]
    assert all(r.json()["transaction_id"] == transaction_id for r in winners)

    from ledger.db import get_session_factory
    from ledger.models import LedgerIdempotencyKey, LedgerTransaction, OutboxEvent

    factory = get_session_factory()
    async with factory() as session:
        transactions = await session.scalar(
            select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.id == uuid.UUID(transaction_id))
        )
        events = await session.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == transaction_id)
        )
        keys = await session.scalar(
            select(func.count()).select_from(LedgerIdempotencyKey).where(LedgerIdempotencyKey.idempotency_key == key)
        )
    assert transactions == 1
    assert events == 1
    assert keys == 1


# --------------------------------------------------------------------------- reentrega al consumidor


async def test_i3_reentrega_de_ledger_posted_aplica_una_sola_vez(ledger_client, wallet_ready) -> None:  # type: ignore[no-untyped-def]
    """At-least-once + deduplicación (ADR-0016): el segundo `apply` devuelve False
    y el saldo no cambia. Evento real del outbox de esta misma ejecución."""
    from ledger.db import get_session_factory as ledger_factory
    from ledger.models import OutboxEvent
    from ledger.outbox import encode_envelope
    from sqlalchemy import select
    from wallet.config import get_wallet_settings
    from wallet.db import get_session_factory as wallet_factory
    from wallet.service import WalletService

    owner = uuid.uuid4()
    body = _body(owner)
    response = await _post(ledger_client, body, str(uuid.uuid4()))
    assert response.status_code == 201
    transaction_id = response.json()["transaction_id"]

    ledger = ledger_factory()
    async with ledger() as session:
        row = (
            await session.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == transaction_id))
        ).scalar_one()
    envelope = EventEnvelope.model_validate(json.loads(encode_envelope(row)))

    wallet = wallet_factory()
    async with wallet() as session:
        service = WalletService(session, get_wallet_settings())
        first_apply = await service.apply_ledger_posted(envelope)
        from sqlalchemy import text

        after_first = (
            await session.execute(
                text("SELECT available FROM wallet.balances WHERE user_id = :u AND currency = 'USD'"), {"u": owner}
            )
        ).scalar_one()
        second_apply = await service.apply_ledger_posted(envelope)
        after_second = (
            await session.execute(
                text("SELECT available FROM wallet.balances WHERE user_id = :u AND currency = 'USD'"), {"u": owner}
            )
        ).scalar_one()

    assert first_apply is True
    assert second_apply is False  # deduplicación por event_id
    assert after_first == after_second  # exactitud Decimal: la reentrega no altera el saldo
