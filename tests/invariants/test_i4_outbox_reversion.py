"""I4 — Reconstrucción y reversión (ADR-0018 §1, L §8 invariante 6/7).

- `outbox` emite exactamente un `LedgerPosted` por transacción committeada
  (property test: N transacciones ⇒ N filas de outbox, sin duplicados).
- Cierre + reversión ⇒ efecto neto cero: los saldos vuelven exactamente al valor
  previo (igualdad exacta con `Decimal`, sin tolerancia).

Alcance honesto: la reconstrucción de PnL/posiciones desde `OrderFilled`/
`PositionClosed`/`PnlRealized` pertenece a la Fase 4 (servicio `trading`), que
aún no existe; se cubre aquí el efecto neto cero sobre el ledger real y el outbox.
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import hypothesis.strategies as st
import pytest
from hypothesis import given
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


def _deposit_body(owner: uuid.UUID, amount: str) -> dict[str, object]:
    return {
        "type": "deposit",
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": OCCURRED,
        "metadata": {"source": "invariants-i4"},
        "entries": [
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": amount, "currency": "USD"},
            {
                "account_code": f"2000.PAYABLE.CLIENT.USD.u_{owner.hex}",
                "direction": "C",
                "amount": amount,
                "currency": "USD",
                "owner_id": str(owner),
            },
        ],
    }


async def _post(client, body: dict[str, object]):  # type: ignore[no-untyped-def]
    response = await client.post(URL, json=body, headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())})
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- outbox 1:1


@given(n=st.integers(min_value=1, max_value=5))
async def test_i4_una_transaccion_un_ledger_posted(ledger_client, n: int) -> None:  # type: ignore[no-untyped-def]
    """Property: N transacciones committeadas ⇒ exactamente N filas de outbox."""
    from ledger.db import get_session_factory
    from ledger.models import OutboxEvent

    transaction_ids: list[str] = []
    for _ in range(n):
        owner = uuid.uuid4()
        posting = await _post(ledger_client, _deposit_body(owner, "10.00"))
        transaction_ids.append(posting["transaction_id"])

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(OutboxEvent.event_type, OutboxEvent.aggregate_id).where(
                    OutboxEvent.aggregate_id.in_(transaction_ids)
                )
            )
        ).all()
    assert len(rows) == n
    assert {row.aggregate_id for row in rows} == set(transaction_ids)
    assert all(row.event_type == "LedgerPosted" for row in rows)

    # Cada evento lleva exactamente los 2 asientos de su transacción (D y C).
    from ledger.models import LedgerEntry

    async with factory() as session:
        entries_per_tx = (
            await session.execute(
                select(LedgerEntry.transaction_id, func.count())
                .where(LedgerEntry.transaction_id.in_([uuid.UUID(tx) for tx in transaction_ids]))
                .group_by(LedgerEntry.transaction_id)
            )
        ).all()
    assert {str(row[0]): row[1] for row in entries_per_tx} == {tx: 2 for tx in transaction_ids}


# --------------------------------------------------------------------------- reversión


async def test_i4_reversion_deja_efecto_neto_cero(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """Depósito + reversión simétrica ⇒ el saldo del propietario vuelve exacto al previo."""
    from ledger.db import get_session_factory
    from ledger.store import compute_owner_balances

    owner = uuid.uuid4()

    async def _balance() -> Decimal:
        factory = get_session_factory()
        async with factory() as session:
            for row_owner, currency, total in await compute_owner_balances(session, owner):
                if row_owner == owner and currency == "USD":
                    return total
        return Decimal(0)

    assert await _balance() == Decimal(0)

    deposit = await _post(ledger_client, _deposit_body(owner, "1000.00"))
    balance_after_deposit = await _balance()
    assert balance_after_deposit == Decimal("1000")

    reversal = {
        "type": "reversal",
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": OCCURRED,
        "metadata": {"source": "invariants-i4"},
        "reverses_tx_id": deposit["transaction_id"],
        "entries": [
            {
                "account_code": f"2000.PAYABLE.CLIENT.USD.u_{owner.hex}",
                "direction": "D",
                "amount": "1000.00",
                "currency": "USD",
                "owner_id": str(owner),
            },
            {"account_code": CONTROL_ASSET, "direction": "C", "amount": "1000.00", "currency": "USD"},
        ],
    }
    posted = await _post(ledger_client, reversal)
    assert posted["reverses_tx_id"] == deposit["transaction_id"]
    assert await _balance() == Decimal(0)  # efecto neto cero exacto, sin tolerancia

    # 1 depósito + 1 reversión ⇒ 2 transacciones ⇒ 2 eventos (1 cada una).
    from ledger.models import OutboxEvent

    factory = get_session_factory()
    async with factory() as session:
        events = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.aggregate_id.in_([deposit["transaction_id"], posted["transaction_id"]]))
        )
    assert events == 2

    # La reversión doble está prohibida (409): el efecto neto no puede repetirse.
    repeat = await ledger_client.post(URL, json=reversal, headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())})
    assert repeat.status_code == 409
    assert await _balance() == Decimal(0)
