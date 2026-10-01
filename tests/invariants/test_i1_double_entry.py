"""I1 — Σ débitos = Σ créditos por transacción (ADR-0018 §1, L §8 invariante 1).

- Validación pura (`validate_posting_rules`) como property test con hypothesis.
- Rechazo HTTP `422` de asientos desbalanceados contra PostgreSQL real.
- Defensa en profundidad en BD: `ledger.ledger_assert_balanced` lanza sobre un
  INSERT desbalanceado que se cuelgue de la validación de aplicación (ADR-0011 §1).
"""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import hypothesis.strategies as st
import pytest
from hypothesis import given
from ledger.postings import PostingRuleError, validate_posting_rules
from platform_kernel.security.tokens import new_service_token

pytestmark = pytest.mark.invariants

URL = "/internal/v1/postings"
OCCURRED = "2026-09-29T12:00:00Z"
CONTROL_ASSET = "1200.RECEIVABLE.PSP.USD"
CLIENT_LIABILITY = "2000.PAYABLE.CLIENT.USD.u1"
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")

SERVICE_TOKEN = new_service_token(
    service_name="identity",
    secret=os.environ["SERVICE_TOKEN_SECRET"],
    issuer="platform-identity",
    audience="platform-internal",
)
HEADERS = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


def _fact(amount: str, direction: str, *, owner: str | None = None) -> dict[str, object]:
    entry: dict[str, object] = {
        "account_code": CLIENT_LIABILITY if owner else CONTROL_ASSET,
        "direction": direction,
        "amount": amount,
        "currency": "USD",
    }
    if owner is not None:
        entry["owner_id"] = owner
    return entry


def _body(entries: list[dict[str, object]], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "deposit",
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": OCCURRED,
        "metadata": {"source": "invariants"},
        "entries": entries,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- property (pura)


@given(total=st.integers(min_value=2, max_value=1_000_000))
def test_i1_posting_balanceado_es_aceptado_y_suma_igual(total: int) -> None:
    """Property: cualquier par D/C con el mismo importe valida y ΣD == ΣC exacto."""
    amount = f"{total // 100}.{total % 100:02d}"
    entries = [_fact(amount, "D"), _fact(amount, "C", owner=str(USER_A))]
    facts = validate_posting_rules(tx_type="deposit", entries=entries, reverses_tx_id=None)

    debits = sum((f.amount for f in facts if f.direction == "D"), Decimal(0))
    credits = sum((f.amount for f in facts if f.direction == "C"), Decimal(0))
    assert debits == credits
    assert [f.position for f in facts] == [1, 2]


@given(
    debit=st.integers(min_value=1, max_value=1_000_000),
    delta=st.integers(min_value=1, max_value=1_000_000),
)
def test_i1_posting_desbalanceado_es_rechazado_pura(debit: int, delta: int) -> None:
    """Property: ΣD != ΣC siempre lanza PostingRuleError (invariante 1)."""
    entries = [
        _fact(f"{debit // 100}.{debit % 100:02d}", "D"),
        _fact(f"{(debit + delta) // 100}.{(debit + delta) % 100:02d}", "C", owner=str(USER_A)),
    ]
    with pytest.raises(PostingRuleError, match="desbalanceados"):
        validate_posting_rules(tx_type="deposit", entries=entries, reverses_tx_id=None)


@given(raw=st.one_of(st.floats(allow_nan=False, allow_infinity=False), st.booleans()))
def test_i1_amount_float_o_bool_es_rechazado(raw: float | bool) -> None:
    """Property: el dinero nunca acepta float ni bool en la entrada (ADR-0006/REQ-015)."""
    with pytest.raises(PostingRuleError, match="float y bool"):
        validate_posting_rules(
            tx_type="deposit",
            entries=[_fact(raw, "D"), _fact("1.00", "C", owner=str(USER_A))],  # type: ignore[arg-type]
            reverses_tx_id=None,
        )


# --------------------------------------------------------------------------- contra PostgreSQL


async def test_i1_posting_desbalanceado_devuelve_422_en_http(ledger_client) -> None:  # type: ignore[no-untyped-def]
    body = _body(
        [
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
    response = await ledger_client.post(URL, json=body, headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())})
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "urn:platform:error:validation"
    assert "desbalanceados" in problem["detail"]


async def test_i1_bd_rechaza_insert_desbalanceado(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """ADR-0011 §1: `ledger_assert_balanced` lanza aunque el INSERT se cuelgue de la app.

    Inserta directamente una transacción con asientos que no cuadran y verifica
    que la función de BD (llamada antes del COMMIT por `store._run`) lanza.
    La excepción aborta la transacción de PostgreSQL, así que el rollback final
    descarta todas las filas sonda: no queda residuo en la BD.
    """
    from ledger.db import get_session_factory
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    factory = get_session_factory()
    async with factory() as session:
        tx_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO ledger.ledger_transactions "
                "(id, type, correlation_id, occurred_at, metadata, created_at) "
                "VALUES (:id, 'deposit', :corr, now(), '{}'::jsonb, now())"
            ),
            {"id": tx_id, "corr": str(uuid.uuid4())},
        )
        await session.execute(
            text(
                "INSERT INTO ledger.ledger_accounts "
                "(id, code, name, type, currency, owner_id, owner_type, is_control, created_at) "
                "VALUES (:id, :code, 'probe', 'asset', 'USD', "
                "'00000000-0000-0000-0000-000000000000', 'system', true, now()) "
                "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name RETURNING id"
            ),
            {"id": uuid.uuid4(), "code": "1000.CASH.USD.i1probe"},
        )
        account = (
            await session.execute(text("SELECT id FROM ledger.ledger_accounts WHERE code = '1000.CASH.USD.i1probe'"))
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO ledger.ledger_entries "
                "(id, transaction_id, account_id, direction, amount, currency, position, created_at) "
                "VALUES (:e1, :tx, :acc, 'D', 100, 'USD', 1, now()), "
                "(:e2, :tx, :acc, 'C', 99, 'USD', 2, now())"
            ),
            {"e1": str(uuid.uuid4()), "e2": str(uuid.uuid4()), "tx": tx_id, "acc": account},
        )
        with pytest.raises(DBAPIError, match="not balanced"):
            await session.execute(text("SELECT ledger.ledger_assert_balanced(CAST(:tx AS uuid))"), {"tx": tx_id})
        await session.rollback()
