"""I5 — Propiedades complementarias (ADR-0018 §1, L §8 invariantes 4/5/8).

- Moneda única por transacción (invariante 4): `deposit` con USD+EUR ⇒ 422.
- `position` 1..N sin huecos ni duplicados (invariante 5), puro y sobre HTTP.
- Moneda del asiento debe coincidir con la moneda de la cuenta existente.
- Activo de control ≥ 0 bajo secuencias **disciplinadas** (depósitos y retiros
  nunca mayores a lo depositado en la misma secuencia).

Nota honesta (L §8, ADR-0007): el ledger **no** valida fondos suficientes; la
suficiencia de fondos la garantizan `wallet`/`accounts` (409 insufficient-balance).
Este test acota la secuencia para que la propiedad sea verificable en el ledger.
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
from sqlalchemy import text

pytestmark = pytest.mark.invariants

URL = "/internal/v1/postings"
OCCURRED = "2026-09-29T12:00:00Z"
CONTROL_USD = "1200.RECEIVABLE.PSP.USD"

SERVICE_TOKEN = new_service_token(
    service_name="identity",
    secret=os.environ["SERVICE_TOKEN_SECRET"],
    issuer="platform-identity",
    audience="platform-internal",
)
HEADERS = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


def _client_code(owner: uuid.UUID) -> str:
    return f"2000.PAYABLE.CLIENT.USD.u_{owner.hex}"


def _entry(
    account_code: str, direction: str, amount: str, currency: str, owner: uuid.UUID | None = None
) -> dict[str, object]:
    entry: dict[str, object] = {
        "account_code": account_code,
        "direction": direction,
        "amount": amount,
        "currency": currency,
    }
    if owner is not None:
        entry["owner_id"] = str(owner)
    return entry


def _body(entries: list[dict[str, object]], *, tx_type: str = "deposit") -> dict[str, object]:
    return {
        "type": tx_type,
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": OCCURRED,
        "metadata": {"source": "invariants-i5"},
        "entries": entries,
    }


async def _post(client, body: dict[str, object]):  # type: ignore[no-untyped-def]
    return await client.post(URL, json=body, headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())})


# --------------------------------------------------------------------------- positions 1..N


@given(n=st.integers(min_value=1, max_value=5), cents=st.integers(min_value=1, max_value=1_000_00))
def test_i5_positions_1_n_sin_huecos(n: int, cents: int) -> None:
    """Property: N débitos + N créditos ⇒ positions exactamente [1, 2, ..., 2N]."""
    amount = f"{cents // 100}.{cents % 100:02d}"
    owner = uuid.uuid4()
    entries = [_entry(CONTROL_USD, "D", amount, "USD") for _ in range(n)]
    entries += [_entry(_client_code(owner), "C", amount, "USD", owner=owner) for _ in range(n)]

    facts = validate_posting_rules(tx_type="deposit", entries=entries, reverses_tx_id=None)
    positions = [fact.position for fact in facts]
    assert positions == list(range(1, 2 * n + 1))
    assert len(set(positions)) == len(positions)  # sin duplicados (uq_tx_position)


async def test_i5_positions_en_http_4_asientos_distintos(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """4 asientos con importes distintos ⇒ positions [1,2,3,4] en la respuesta."""
    owner_a, owner_b = uuid.uuid4(), uuid.uuid4()
    body = _body(
        [
            _entry(CONTROL_USD, "D", "40.00", "USD"),
            _entry(_client_code(owner_a), "D", "60.00", "USD", owner=owner_a),
            _entry(_client_code(owner_b), "C", "30.00", "USD", owner=owner_b),
            _entry(_client_code(owner_a), "C", "70.00", "USD", owner=owner_a),
        ]
    )
    response = await _post(ledger_client, body)
    assert response.status_code == 201, response.text
    positions = [entry["position"] for entry in response.json()["entries"]]
    assert positions == [1, 2, 3, 4]


# --------------------------------------------------------------------------- moneda única


@given(
    usd_cents=st.integers(min_value=1, max_value=1_000_00),
    eur_cents=st.integers(min_value=1, max_value=1_000_00),
)
def test_i5_deposito_multimoneda_es_rechazado_pura(usd_cents: int, eur_cents: int) -> None:
    """Property: deposit con USD+EUR siempre lanza PostingRuleError (invariante 4)."""
    owner = uuid.uuid4()
    entries = [
        _entry(CONTROL_USD, "D", f"{usd_cents // 100}.{usd_cents % 100:02d}", "USD"),
        _entry(
            f"2000.PAYABLE.CLIENT.EUR.u_{owner.hex}",
            "C",
            f"{eur_cents // 100}.{eur_cents % 100:02d}",
            "EUR",
            owner=owner,
        ),
    ]
    with pytest.raises(PostingRuleError, match="no admite más de una moneda"):
        validate_posting_rules(tx_type="deposit", entries=entries, reverses_tx_id=None)


async def test_i5_deposito_multimoneda_devuelve_422_en_http(ledger_client) -> None:  # type: ignore[no-untyped-def]
    owner = uuid.uuid4()
    body = _body(
        [
            _entry(CONTROL_USD, "D", "10.00", "USD"),
            _entry(f"2000.PAYABLE.CLIENT.EUR.u_{owner.hex}", "C", "10.00", "EUR", owner=owner),
        ]
    )
    response = await _post(ledger_client, body)
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "urn:platform:error:validation"
    assert "no admite más de una moneda" in problem["detail"]


# --------------------------------------------------------------------------- moneda de la cuenta


async def test_i5_asiento_con_moneda_distinta_a_la_cuenta_devuelve_422(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """La cuenta de control `...PSP.USD` ya existe en USD; reutilizarla con EUR ⇒ 422.

    El posting completo se declara en una sola moneda (EUR) para que el rechazo
    provenga de la coherencia cuenta/asiento y no de la regla multimoneda.
    """
    owner_a, owner_b = uuid.uuid4(), uuid.uuid4()
    seed = _body(
        [_entry(CONTROL_USD, "D", "10.00", "USD"), _entry(_client_code(owner_a), "C", "10.00", "USD", owner=owner_a)]
    )
    assert (await _post(ledger_client, seed)).status_code == 201

    mismatch = _body(
        [
            _entry(CONTROL_USD, "D", "5.00", "EUR"),
            _entry(f"2000.PAYABLE.CLIENT.EUR.u_{owner_b.hex}", "C", "5.00", "EUR", owner=owner_b),
        ]
    )
    response = await _post(ledger_client, mismatch)
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "urn:platform:error:validation"
    assert f"la cuenta '{CONTROL_USD}' está en 'USD'; el asiento usa 'EUR'" in problem["detail"]


# --------------------------------------------------------------------------- activo de control >= 0


async def _control_balance() -> Decimal:
    from ledger.db import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(CASE WHEN e.direction = 'D' THEN e.amount ELSE -e.amount END), 0) "
                    "FROM ledger.ledger_entries e JOIN ledger.ledger_accounts a ON e.account_id = a.id "
                    "WHERE a.code = :code"
                ),
                {"code": CONTROL_USD},
            )
        ).scalar_one()
    return Decimal(row)


@given(
    ops=st.lists(
        st.tuples(st.sampled_from(["deposit", "withdraw"]), st.integers(min_value=1, max_value=500_00)),
        max_size=8,
    )
)
async def test_i5_activo_control_no_negativo_bajo_secuencia_disciplinada(ledger_client, ops) -> None:  # type: ignore[no-untyped-def]
    """Property: secuencia disciplinada ⇒ `1200.RECEIVABLE.PSP.USD` nunca baja de su valor inicial.

    Solo retiros ejecutables (≤ neto acumulado de esta secuencia). El ledger no
    valida fondos (L §8), por eso la disciplina la impone el test, como haría
    `wallet`/`accounts` en el flujo real.
    """
    owner = uuid.uuid4()
    net = 0
    before = await _control_balance()

    for kind, cents in ops:
        amount = f"{cents // 100}.{cents % 100:02d}"
        if kind == "withdraw":
            if cents > net:
                continue  # retiro no ejecutable bajo la disciplina impuesta
            body = _body(
                [_entry(_client_code(owner), "D", amount, "USD", owner=owner), _entry(CONTROL_USD, "C", amount, "USD")],
                tx_type="withdrawal",
            )
            net -= cents
        else:
            body = _body(
                [_entry(CONTROL_USD, "D", amount, "USD"), _entry(_client_code(owner), "C", amount, "USD", owner=owner)]
            )
            net += cents
        response = await _post(ledger_client, body)
        assert response.status_code == 201, response.text

    after = await _control_balance()
    assert after >= before, f"activo de control bajó de su valor inicial: {after} < {before}"

    from ledger.db import get_session_factory
    from ledger.store import compute_owner_balances

    factory = get_session_factory()
    async with factory() as session:
        balances = {(owner_id, currency): total for owner_id, currency, total in await compute_owner_balances(session)}
    assert balances.get((owner, "USD"), Decimal(0)) == Decimal(net) / 100
