"""I2 — Los saldos solo cambian mediante asientos del ledger (ADR-0018 §1, L §8 inv. 2/3).

Property test con hypothesis: secuencias aleatorias de depósitos, retiros y
transferencias ejecutadas contra PostgreSQL real. El saldo por propietario es
siempre la derivación exacta `Σ créditos - Σ débitos` (calculada en el test en
centavos enteros) y la proyección `wallet` aplicada con los `LedgerPosted` del
outbox coincide con el ledger. Verificación adicional: `UPDATE`/`DELETE` sobre
`ledger_entries`/`ledger_transactions` están prohibidos (ORM y trigger de BD).
"""

from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal

import hypothesis.strategies as st
import pytest
from hypothesis import given
from ihelpers import amount_strategy, cents
from ledger.outbox import encode_envelope
from platform_kernel.security.tokens import new_service_token
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError

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


def _client_code(owner: uuid.UUID) -> str:
    return f"2000.PAYABLE.CLIENT.USD.u_{owner.hex}"


def _body(entries: list[dict[str, object]], *, tx_type: str = "deposit") -> dict[str, object]:
    return {
        "type": tx_type,
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": OCCURRED,
        "metadata": {"source": "invariants-i2"},
        "entries": entries,
    }


async def _post(client, body: dict[str, object]) -> uuid.UUID:  # type: ignore[no-untyped-def]
    response = await client.post(URL, json=body, headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())})
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["transaction_id"])


# --------------------------------------------------------------------------- property


@given(ops=st.lists(st.tuples(st.sampled_from(["deposit", "withdrawal", "transfer"]), amount_strategy()), max_size=8))
async def test_i2_saldos_igualan_suma_de_asientos_y_wallet_coincide(  # type: ignore[no-untyped-def]
    ledger_client, wallet_ready, ops: list[tuple[str, str]]
) -> None:
    """Property: para cualquier secuencia ejecutable, saldo == Σ entries (exacto en
    centavos) y la proyección wallet, aplicada con los eventos reales del outbox,
    produce exactamente los mismos saldos que el ledger."""
    from ledger.db import get_session_factory as ledger_factory
    from ledger.models import OutboxEvent
    from ledger.store import compute_owner_balances
    from sqlalchemy import select
    from wallet.config import get_wallet_settings
    from wallet.db import get_session_factory as wallet_factory
    from wallet.service import WalletService

    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    expected: dict[uuid.UUID, int] = {owner_a: 0, owner_b: 0}
    transaction_ids: list[str] = []

    for kind, amount_str in ops:
        amount_cents = cents(amount_str)
        if kind == "deposit":
            transaction_ids.append(
                str(
                    await _post(
                        ledger_client,
                        _body(
                            [
                                {
                                    "account_code": CONTROL_ASSET,
                                    "direction": "D",
                                    "amount": amount_str,
                                    "currency": "USD",
                                },
                                {
                                    "account_code": _client_code(owner_a),
                                    "direction": "C",
                                    "amount": amount_str,
                                    "currency": "USD",
                                    "owner_id": str(owner_a),
                                },
                            ]
                        ),
                    )
                )
            )
            expected[owner_a] += amount_cents
        elif kind == "withdrawal":
            if amount_cents > expected[owner_a]:
                continue  # retiro no ejecutable (el ledger no valida fondos; el test no lo genera)
            transaction_ids.append(
                str(
                    await _post(
                        ledger_client,
                        _body(
                            [
                                {
                                    "account_code": _client_code(owner_a),
                                    "direction": "D",
                                    "amount": amount_str,
                                    "currency": "USD",
                                    "owner_id": str(owner_a),
                                },
                                {
                                    "account_code": CONTROL_ASSET,
                                    "direction": "C",
                                    "amount": amount_str,
                                    "currency": "USD",
                                },
                            ],
                            tx_type="withdrawal",
                        ),
                    )
                )
            )
            expected[owner_a] -= amount_cents
        else:  # transfer
            if amount_cents > expected[owner_a]:
                continue
            transaction_ids.append(
                str(
                    await _post(
                        ledger_client,
                        _body(
                            [
                                {
                                    "account_code": _client_code(owner_a),
                                    "direction": "D",
                                    "amount": amount_str,
                                    "currency": "USD",
                                    "owner_id": str(owner_a),
                                },
                                {
                                    "account_code": _client_code(owner_b),
                                    "direction": "C",
                                    "amount": amount_str,
                                    "currency": "USD",
                                    "owner_id": str(owner_b),
                                },
                            ],
                            tx_type="transfer",
                        ),
                    )
                )
            )
            expected[owner_a] -= amount_cents
            expected[owner_b] += amount_cents

    # 1) El ledger devuelve exactamente la derivación ΣC - ΣD (centavos enteros).
    ledger = ledger_factory()
    async with ledger() as session:
        balances = {(owner, currency): total for owner, currency, total in await compute_owner_balances(session)}
    for owner, expected_cents in expected.items():
        got = balances.get((owner, "USD"), Decimal(0))
        assert got == Decimal(expected_cents) / 100, f"ledger: {got} != derivación {expected_cents} centavos"

    # 2) La proyección wallet, alimentada con los LedgerPosted reales, coincide.
    async with ledger() as session:
        rows = (
            (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.aggregate_id.in_(transaction_ids))
                    .order_by(OutboxEvent.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == len(transaction_ids)  # invariante 7: 1 tx ⇒ 1 LedgerPosted

    wallet = wallet_factory()
    async with wallet() as session:
        service = WalletService(session, get_wallet_settings())
        for row in rows:
            envelope = json.loads(encode_envelope(row))
            from platform_kernel.events import EventEnvelope

            applied = await service.apply_ledger_posted(EventEnvelope.model_validate(envelope))
            assert applied is True
        result = (
            await session.execute(
                text("SELECT user_id, available FROM wallet.balances WHERE user_id IN (:a, :b) AND currency = 'USD'"),
                {"a": owner_a, "b": owner_b},
            )
        ).all()
    wallet_balances = {row[0]: row[1] for row in result}
    for owner, expected_cents in expected.items():
        got = wallet_balances.get(owner, Decimal(0))
        assert got == Decimal(expected_cents) / 100, f"wallet: {got} != derivación {expected_cents} centavos"


# --------------------------------------------------------------------------- append-only


async def test_i2_update_y_delete_sobre_asientos_estan_prohibidos(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """ADR-0011 §2: ninguna ruta altera asientos/transacciones ya escritos.

    Red de aplicación (event listeners de `ledger.models`) y red de BD (trigger
    `ledger_forbid_mutation` con ERRCODE 42501) deben rechazar UPDATE y DELETE.
    """
    from ledger.db import get_session_factory
    from ledger.models import LedgerEntry, LedgerTransaction

    body = {
        "type": "deposit",
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": OCCURRED,
        "metadata": {"source": "invariants-i2-append"},
        "entries": [
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": "10.00", "currency": "USD"},
            {
                "account_code": "2000.PAYABLE.CLIENT.USD.u_" + uuid.uuid4().hex,
                "direction": "C",
                "amount": "10.00",
                "currency": "USD",
                "owner_id": str(uuid.uuid4()),
            },
        ],
    }
    response = await ledger_client.post(URL, json=body, headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())})
    assert response.status_code == 201
    transaction_id = response.json()["transaction_id"]

    factory = get_session_factory()
    async with factory() as session:
        entry_id = (
            await session.execute(
                text("SELECT id FROM ledger.ledger_entries WHERE transaction_id = CAST(:tx AS uuid) LIMIT 1"),
                {"tx": transaction_id},
            )
        ).scalar_one()

        # Capa ORM: listeners before_update/before_delete (models._forbid).
        entry = await session.get(LedgerEntry, uuid.UUID(str(entry_id)))
        assert entry is not None
        entry.amount = Decimal("999.00")
        with pytest.raises(RuntimeError, match="append-only"):
            await session.flush()
        await session.rollback()

        transaction = await session.get(LedgerTransaction, uuid.UUID(transaction_id))
        assert transaction is not None
        await session.delete(transaction)
        with pytest.raises(RuntimeError, match="append-only"):
            await session.flush()
        await session.rollback()

        # Capa BD: trigger con ERRCODE 42501 (defensa aunque se obvie el ORM).
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(
                update(LedgerEntry).where(LedgerEntry.id == uuid.UUID(str(entry_id))).values(amount=Decimal("1"))
            )
        await session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(
                text("DELETE FROM ledger.ledger_entries WHERE id = CAST(:id AS uuid)"), {"id": entry_id}
            )
        await session.rollback()
