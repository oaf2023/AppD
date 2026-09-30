"""Pruebas unitarias del Ledger Service (sin PostgreSQL ni Redpanda).

El fichero no se llama `test_ledger.py` para evitar la colisión de nombre de
módulo con `tests/integration/test_ledger.py` (pytest importa los directorios
sin `__init__.py`).

Contrasta `ledger.postings`, `ledger.schemas`, `ledger.config` y `ledger.metrics`
con `L-ledger-architecture.md` §1/§2.2/§3/§7/§8, ADR-0006 (dinero como cadena),
ADR-0010 (idempotencia) y ADR-0018 (tests de invariantes financieros).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from ledger.config import IDEMPOTENCY_TTL_SECONDS, LedgerSettings
from ledger.metrics import POSTINGS_TOTAL, _shared_metric
from ledger.postings import (
    SYSTEM_OWNER_ID,
    EntryFact,
    PostingRuleError,
    ResolvedEntry,
    advisory_lock_key,
    build_ledger_posted_payload,
    canonical_amount,
    normalize_direction,
    parse_amount,
    plan_for_code,
    posting_request_hash,
    validate_posting_rules,
)
from ledger.schemas import PostingsIn
from platform_contracts.events import topic_for_event
from prometheus_client import Counter, Gauge
from pydantic import ValidationError

OWNER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
CORRELATION = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
OCCURRED = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)

CONTROL_ASSET = "1200.RECEIVABLE.PSP.USD"
CLIENT_LIABILITY = "2000.PAYABLE.CLIENT.USD.u1"


def _entry(code: str, direction: str, amount: str, currency: str = "USD", **extra: object) -> dict[str, object]:
    data: dict[str, object] = {
        "account_code": code,
        "direction": direction,
        "amount": amount,
        "currency": currency,
    }
    data.update(extra)
    return data


def _deposit_entries(amount: str = "1000.00") -> list[dict[str, object]]:
    return [
        _entry(CONTROL_ASSET, "D", amount),
        _entry(CLIENT_LIABILITY, "C", amount, owner_id=OWNER_A),
    ]


def _validate(
    tx_type: str,
    entries: list[dict[str, object]],
    reverses_tx_id: uuid.UUID | None = None,
) -> list[EntryFact]:
    return validate_posting_rules(tx_type=tx_type, entries=entries, reverses_tx_id=reverses_tx_id)


def _hash(entries: list[dict[str, object]], subject: str = "identity") -> str:
    return posting_request_hash(
        tx_type="deposit",
        correlation_id=CORRELATION,
        causation_id=None,
        occurred_at=OCCURRED,
        metadata={"source": "test"},
        reverses_tx_id=None,
        entries=entries,
        subject=subject,
    )


def _command(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "deposit",
        "correlation_id": str(CORRELATION),
        "occurred_at": "2026-09-29T12:00:00Z",
        "metadata": {"source": "test"},
        "entries": _deposit_entries(),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- dinero (ADR-0006)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1000.00"), "1000"),
        (Decimal("10.50"), "10.5"),
        (Decimal("100"), "100"),
        (Decimal("0"), "0"),
        (Decimal("0.000000000000000001"), "0.000000000000000001"),
        (Decimal("0.10"), "0.1"),
        (Decimal("-12.3400"), "-12.34"),
    ],
)
def test_canonical_amount_sin_ceros_a_la_derecha(value: Decimal, expected: str) -> None:
    assert canonical_amount(value) == expected


def test_parse_amount_acepta_cadena_entera_y_decimal() -> None:
    assert parse_amount("1000.00") == Decimal("1000.00")
    assert parse_amount("42") == Decimal("42")
    assert parse_amount(7) == Decimal("7")


@pytest.mark.parametrize("raw", [1.5, 1.0, True, False])
def test_parse_amount_rechaza_float_y_bool(raw: object) -> None:
    with pytest.raises(PostingRuleError, match="float y bool"):
        parse_amount(raw)


@pytest.mark.parametrize("raw", ["0", "-1", "0.00"])
def test_parse_amount_exige_positivo(raw: str) -> None:
    with pytest.raises(PostingRuleError, match="mayor que cero"):
        parse_amount(raw)


def test_parse_amount_rechaza_no_finitos() -> None:
    with pytest.raises(PostingRuleError, match="finito"):
        parse_amount("NaN")
    with pytest.raises(PostingRuleError, match="finito"):
        parse_amount("Infinity")


def test_parse_amount_respeta_escala_y_digitos() -> None:
    parse_amount("0." + "0" * 17 + "1")  # escala 18: límite permitido
    with pytest.raises(PostingRuleError, match="escala de 18"):
        parse_amount("0." + "0" * 18 + "1")
    with pytest.raises(PostingRuleError, match="20 dígitos enteros"):
        parse_amount("1" * 21)


def test_parse_amount_rechaza_texto() -> None:
    with pytest.raises(PostingRuleError, match="amount inválido"):
        parse_amount("mil")
    with pytest.raises(PostingRuleError, match="cadena decimal"):
        parse_amount(None)


# --------------------------------------------------------------------------- dirección (L §1)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("D", "D"), ("d", "D"), ("debit", "D"), ("DEBIT", "D"), ("C", "C"), ("credit", "C"), (" credit ", "C")],
)
def test_normalize_direction_alias_insensibles_a_mayusculas(raw: str, expected: str) -> None:
    assert normalize_direction(raw) == expected


@pytest.mark.parametrize("raw", ["", "x", "1", 1, None])
def test_normalize_direction_rechaza_desconocidos(raw: object) -> None:
    with pytest.raises(PostingRuleError, match="dirección inválida"):
        normalize_direction(raw)


# --------------------------------------------------------------------------- plan de cuentas (L §7.1)


@pytest.mark.parametrize(
    ("code", "type_", "is_control"),
    [
        ("1000.CASH.USD", "asset", True),
        ("1100.MARGIN.USD", "asset", True),
        ("1200.RECEIVABLE.PSP.USD", "asset", True),
        ("2000.PAYABLE.CLIENT.USD.u1", "liability", False),
        ("2100.PAYABLE.PSP.USD", "liability", True),
        ("3000.EQUITY.PNL.USD", "equity", True),
        ("4000.REVENUE.FEE.USD", "revenue", True),
        ("4100.REVENUE.SWAP.USD", "revenue", True),
        ("5000.EXPENSE.PSP.USD", "expense", True),
    ],
)
def test_plan_de_cuentas_por_prefijo(code: str, type_: str, is_control: bool) -> None:
    plan = plan_for_code(code)
    assert plan.type == type_
    assert plan.is_control is is_control


def test_plan_rechaza_prefijo_fuera_del_catalogo() -> None:
    with pytest.raises(PostingRuleError, match="fuera del plan"):
        plan_for_code("9999.CRYPTO.USD")


@pytest.mark.parametrize("code", ["1000", "cash.USD", "1000.", "1000.a-b", "10a0.CASH.USD"])
def test_plan_rechaza_codigo_mal_formado(code: str) -> None:
    with pytest.raises(PostingRuleError, match="código de cuenta inválido"):
        plan_for_code(code)


def test_desviacion_regla_2_2_admite_cuentas_de_las_secciones_7_1_y_7_2() -> None:
    """Desviación documentada: L §2.2 exige `NNNN.X.CCC` pero §7.1 usa `2000.PAYABLE.CLIENT`."""
    assert plan_for_code("2000.PAYABLE.CLIENT").is_control is False
    assert plan_for_code("2000.PAYABLE.CLIENT.USD.u1").is_control is False


# --------------------------------------------------------------------------- reglas de asiento (L §1/§3/§8)


def test_posting_valido_produce_hechos_en_posiciones_1_y_2() -> None:
    facts = _validate("deposit", _deposit_entries())
    assert [f.position for f in facts] == [1, 2]
    assert facts[0].direction == "D"
    assert facts[1].direction == "C"
    assert facts[0].amount == Decimal("1000.00")
    # cuentas de control → propietario del sistema (L §7.1)
    assert facts[0].owner_id == SYSTEM_OWNER_ID
    assert facts[0].owner_type == "system"
    # cuentas no control → exigen owner_id
    assert facts[1].owner_id == OWNER_A
    assert facts[1].owner_type == "user"


def test_posting_requiere_al_menos_dos_asientos() -> None:
    with pytest.raises(PostingRuleError, match="al menos 2 asientos"):
        _validate("deposit", [_entry(CONTROL_ASSET, "D", "10")])


def test_posting_desbalanceado_rechazado() -> None:
    with pytest.raises(PostingRuleError, match="asientos desbalanceados"):
        _validate(
            "deposit",
            [
                _entry(CONTROL_ASSET, "D", "1000.00"),
                _entry(CLIENT_LIABILITY, "C", "999.00", owner_id=OWNER_A),
            ],
        )


def test_transaccion_con_una_sola_moneda() -> None:
    with pytest.raises(PostingRuleError, match="no admite más de una moneda"):
        _validate(
            "transfer",
            [
                _entry(CONTROL_ASSET, "D", "100", "USD"),
                _entry(CONTROL_ASSET, "C", "100", "EUR"),
            ],
        )


def test_conversion_multimoneda_admitida_y_balance_global() -> None:
    """L §7.5: conversión FX con comisión; balance global ΣD = ΣC (ADR-0011 §1)."""
    facts = _validate(
        "conversion",
        [
            _entry(CLIENT_LIABILITY, "D", "928", "USD", owner_id=OWNER_A),
            _entry("2000.PAYABLE.CLIENT.EUR.u1", "C", "920", "EUR", owner_id=OWNER_A),
            _entry("4000.REVENUE.FEE.USD", "C", "8", "USD"),
        ],
    )
    assert {f.currency for f in facts} == {"USD", "EUR"}


def test_reversal_exige_reverses_tx_id() -> None:
    with pytest.raises(PostingRuleError, match="exige reverses_tx_id"):
        _validate("reversal", _deposit_entries(), reverses_tx_id=None)


def test_reverses_tx_id_solo_para_reversal() -> None:
    with pytest.raises(PostingRuleError, match="solo type='reversal' admite"):
        _validate("deposit", _deposit_entries(), reverses_tx_id=uuid.uuid4())


def test_tipo_de_transaccion_desconocido() -> None:
    with pytest.raises(PostingRuleError, match="tipo de transacción inválido"):
        _validate("airdrop", _deposit_entries())


def test_cuenta_de_control_rechaza_owner_id() -> None:
    with pytest.raises(PostingRuleError, match="no admite owner_id"):
        _validate(
            "deposit",
            [
                _entry(CONTROL_ASSET, "D", "10", owner_id=OWNER_A),
                _entry(CLIENT_LIABILITY, "C", "10", owner_id=OWNER_A),
            ],
        )


def test_cuenta_no_control_requiere_owner_id() -> None:
    with pytest.raises(PostingRuleError, match="requiere owner_id"):
        _validate(
            "deposit",
            [
                _entry(CONTROL_ASSET, "D", "10"),
                _entry(CLIENT_LIABILITY, "C", "10"),
            ],
        )


def test_owner_type_restringido_a_user_o_tenant() -> None:
    with pytest.raises(PostingRuleError, match="owner_type inválido"):
        _validate(
            "deposit",
            [
                _entry(CONTROL_ASSET, "D", "10"),
                _entry(CLIENT_LIABILITY, "C", "10", owner_id=OWNER_A, owner_type="guest"),
            ],
        )


def test_direccion_invalida_rechazada_por_las_reglas() -> None:
    with pytest.raises(PostingRuleError, match="dirección inválida"):
        _validate(
            "deposit",
            [
                _entry(CONTROL_ASSET, "X", "10"),
                _entry(CLIENT_LIABILITY, "C", "10", owner_id=OWNER_A),
            ],
        )


def test_importe_numerico_no_pasa_por_las_reglas() -> None:
    with pytest.raises(PostingRuleError, match="float y bool"):
        _validate(
            "deposit",
            [
                _entry(CONTROL_ASSET, "D", 10.0),
                _entry(CLIENT_LIABILITY, "C", "10", owner_id=OWNER_A),
            ],
        )


def test_currency_iso_4217_obligatoria() -> None:
    with pytest.raises(PostingRuleError, match="currency inválida"):
        _validate(
            "deposit",
            [
                _entry(CONTROL_ASSET, "D", "10", "usd"),
                _entry(CLIENT_LIABILITY, "C", "10", "usd", owner_id=OWNER_A),
            ],
        )


# --------------------------------------------------------------------------- idempotencia (ADR-0010)


def test_hash_determinista_para_el_mismo_comando() -> None:
    entries = _deposit_entries()
    assert _hash(entries) == _hash(_deposit_entries())


def test_hash_sensible_al_sujeto_autenticado() -> None:
    entries = _deposit_entries()
    assert _hash(entries, subject="identity") != _hash(entries, subject="payments")


def test_hash_canonico_ignora_escala_y_alias_de_direccion() -> None:
    importe_variable = [
        _entry(CONTROL_ASSET, "debit", "1000.0"),
        _entry(CLIENT_LIABILITY, "CREDIT", "1000.000", owner_id=OWNER_A),
    ]
    assert _hash(_deposit_entries()) == _hash(importe_variable)
    distinto = _deposit_entries("1000.01")
    assert _hash(_deposit_entries()) != _hash(distinto)


def test_hash_sensible_a_correlacion() -> None:
    entries = _deposit_entries()
    base = _hash(entries)
    otro = posting_request_hash(
        tx_type="deposit",
        correlation_id=uuid.UUID("00000000-0000-0000-0000-0000000000c2"),
        causation_id=None,
        occurred_at=OCCURRED,
        metadata={"source": "test"},
        reverses_tx_id=None,
        entries=entries,
        subject="identity",
    )
    assert base != otro


def test_advisory_lock_key_estable_y_acotado_a_int8() -> None:
    key = str(uuid.uuid4())
    first = advisory_lock_key(key)
    assert first == advisory_lock_key(key)
    assert advisory_lock_key(f"{key}x") != first
    assert -(2**63) <= first < 2**63


def test_ttl_de_claves_de_idempotencia_es_siete_dias() -> None:
    assert IDEMPOTENCY_TTL_SECONDS == 7 * 24 * 60 * 60
    assert LedgerSettings().idempotency_ttl_seconds == IDEMPOTENCY_TTL_SECONDS


# --------------------------------------------------------------------------- contratos HTTP


def test_postings_in_acepta_el_comando_valido() -> None:
    command = PostingsIn.model_validate(_command())
    assert command.type == "deposit"
    assert len(command.entries) == 2


def test_postings_in_convierte_a_utc() -> None:
    command = PostingsIn.model_validate(_command(occurred_at="2026-09-29T09:00:00-03:00"))
    assert command.occurred_at.tzinfo is not None
    assert command.occurred_at.utcoffset().total_seconds() == 0
    sin_zona = PostingsIn.model_validate(_command(occurred_at="2026-09-29T09:00:00"))
    assert sin_zona.occurred_at.tzinfo is not None


def test_postings_in_rechaza_importe_numerico() -> None:
    """ADR-0006: un número JSON no es dinero; FastAPI responde 422."""
    with pytest.raises(ValidationError) as excinfo:
        PostingsIn.model_validate(
            _command(
                entries=[
                    _entry(CONTROL_ASSET, "D", 1000.5),
                    _entry(CLIENT_LIABILITY, "C", "1000.5", owner_id=OWNER_A),
                ]
            )
        )
    assert excinfo.value.errors()[0]["loc"][-1] == "amount"


def test_postings_in_rechaza_campos_desconocidos() -> None:
    with pytest.raises(ValidationError) as excinfo:
        PostingsIn.model_validate(_command(suspicious=True))
    assert excinfo.value.errors()[0]["type"] == "extra_forbidden"


def test_postings_in_exige_minimo_dos_asientos() -> None:
    with pytest.raises(ValidationError) as excinfo:
        PostingsIn.model_validate(_command(entries=[_entry(CONTROL_ASSET, "D", "10")]))
    assert excinfo.value.errors()[0]["type"] == "too_short"


def test_postings_in_rechaza_tipo_fuera_del_catalogo() -> None:
    with pytest.raises(ValidationError) as excinfo:
        PostingsIn.model_validate(_command(type="airdrop"))
    assert excinfo.value.errors()[0]["type"] == "literal_error"


# --------------------------------------------------------------------------- evento LedgerPosted (P #38)


def test_topic_de_ledger_posted() -> None:
    assert topic_for_event("ledger", "LedgerTransaction", "LedgerPosted") == "ledger.ledger_transaction.ledger_posted"


def test_payload_de_ledger_posted_con_importe_canonico() -> None:
    transaction_id = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
    control = ResolvedEntry(
        entry_id=uuid.uuid4(),
        position=1,
        account_id=uuid.uuid4(),
        account_code=CONTROL_ASSET,
        direction="D",
        amount=Decimal("1000.000000000000000000"),
        currency="USD",
    )
    cliente = ResolvedEntry(
        entry_id=uuid.uuid4(),
        position=2,
        account_id=uuid.uuid4(),
        account_code=CLIENT_LIABILITY,
        direction="C",
        amount=Decimal("1000.000000000000000000"),
        currency="USD",
        owner_id=OWNER_A,
        owner_type="user",
    )
    payload = build_ledger_posted_payload(
        transaction_id=transaction_id,
        tx_type="deposit",
        correlation_id=CORRELATION,
        occurred_at=OCCURRED,
        entries=[control, cliente],
    )
    assert payload["transaction_id"] == str(transaction_id)
    assert payload["type"] == "deposit"
    assert payload["occurred_at"] == OCCURRED.isoformat()
    # P #38: owner_id/owner_type identifican al titular (wallet filtra por owner_type)
    assert payload["entries"] == [
        {
            "account_id": str(control.account_id),
            "direction": "D",
            "amount": "1000",
            "currency": "USD",
            "owner_id": None,
            "owner_type": None,
        },
        {
            "account_id": str(cliente.account_id),
            "direction": "C",
            "amount": "1000",
            "currency": "USD",
            "owner_id": str(OWNER_A),
            "owner_type": "user",
        },
    ]


# --------------------------------------------------------------------------- métricas y backoff


def test_metrica_de_postings_es_unico_por_nombre() -> None:
    again = _shared_metric(
        Counter,
        "platform_ledger_postings_total",
        "Postings registrados en el ledger",
        ["type"],
    )
    assert again is POSTINGS_TOTAL
    assert POSTINGS_TOTAL.labels("deposit") is not None


def test_metricas_outbox_compartidas_con_identity() -> None:
    """`identity.outbox` usa constructores planos: ledger debe reutilizarlos (no duplicar)."""
    from identity.outbox import BACKLOG_GAUGE as IDENTITY_BACKLOG
    from ledger.outbox import BACKLOG_GAUGE as LEDGER_BACKLOG

    assert LEDGER_BACKLOG is IDENTITY_BACKLOG
    shared = _shared_metric(
        Gauge,
        "platform_outbox_backlog",
        "Eventos del outbox pendientes de publicar o enviar a la DLQ",
        ["service"],
    )
    assert shared is LEDGER_BACKLOG


def test_backoff_exponencial_con_jitter_cero() -> None:
    from ledger.outbox import compute_backoff_ms

    serie = [compute_backoff_ms(attempt, base_ms=500, jitter=0.0) for attempt in range(1, 8)]
    assert serie == [500, 1000, 2000, 4000, 8000, 16000, 32000]


def test_backoff_acotado_al_maximo() -> None:
    from ledger.outbox import compute_backoff_ms

    assert compute_backoff_ms(30, base_ms=1000, max_ms=60_000, jitter=0.0) == 60_000
    assert compute_backoff_ms(0, base_ms=1000, jitter=0.0) >= 1


def test_backoff_con_jitter_no_sale_del_rango() -> None:
    import random

    from ledger.outbox import compute_backoff_ms

    base = 400 * (2**2)
    rng = random.Random(7)
    for _ in range(50):
        value = compute_backoff_ms(3, base_ms=400, jitter=0.25, rng=rng)
        assert base * 0.75 - 1 <= value <= base * 1.25
