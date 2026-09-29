"""postings — lógica pura de asientos double-entry (sin I/O, sin FastAPI).

Reglas de negocio verificables en `docs/phase0/L-ledger-architecture.md` §1,
§3, §7 y §8 (invariantes 1, 4, 6, 9 y 10). Cualquier violación se comunica
como `PostingRuleError` y la capa HTTP la traduce a `422`.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

from platform_kernel.idempotency import request_hash
from platform_kernel.money import to_decimal

from ledger.models import ACCOUNT_TYPES, ENTRY_DIRECTIONS, TX_TYPES

# --------------------------------------------------------------------------- constantes

MULTI_CURRENCY_TX_TYPES: Final[frozenset[str]] = frozenset({"conversion", "reversal"})

ACCOUNT_CODE_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]{4}\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")
CURRENCY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{3}$")

MAX_AMOUNT_INTEGER_DIGITS: Final[int] = 20
MAX_AMOUNT_SCALE: Final[int] = 18

SYSTEM_OWNER_ID: Final[uuid.UUID] = uuid.UUID(int=0)

_DIRECTION_ALIASES: Final[dict[str, Literal["D", "C"]]] = {
    "d": "D",
    "debit": "D",
    "c": "C",
    "credit": "C",
}

__all__ = [
    "ACCOUNT_CODE_RE",
    "ACCOUNT_TYPES",
    "CURRENCY_RE",
    "ENTRY_DIRECTIONS",
    "MAX_AMOUNT_INTEGER_DIGITS",
    "MAX_AMOUNT_SCALE",
    "MULTI_CURRENCY_TX_TYPES",
    "SYSTEM_OWNER_ID",
    "TX_TYPES",
    "EntryFact",
    "PlanAccount",
    "PostingRuleError",
    "ResolvedEntry",
    "build_ledger_posted_payload",
    "canonical_amount",
    "canonical_request",
    "normalize_direction",
    "parse_amount",
    "plan_for_code",
    "posting_request_hash",
    "validate_posting_rules",
]


class PostingRuleError(ValueError):
    """Violación de una regla de asiento (la capa HTTP la traduce a 422)."""


# --------------------------------------------------------------------------- plan de cuentas


@dataclass(frozen=True)
class PlanAccount:
    """Entrada del plan de cuentas base (L §7.1) indexada por prefijo de 4 dígitos."""

    name: str
    type: str
    is_control: bool


PLAN_DE_CUENTAS: Final[dict[str, PlanAccount]] = {
    "1000": PlanAccount("Efectivo", "asset", True),
    "1100": PlanAccount("Margen depositado", "asset", True),
    "1200": PlanAccount("Por cobrar PSP", "asset", True),
    "2000": PlanAccount("Por pagar clientes", "liability", False),
    "2100": PlanAccount("Por pagar PSP", "liability", True),
    "3000": PlanAccount("PnL realizado", "equity", True),
    "4000": PlanAccount("Ingresos comisiones", "revenue", True),
    "4100": PlanAccount("Ingresos swap", "revenue", True),
    "5000": PlanAccount("Gastos PSP", "expense", True),
}


def plan_for_code(account_code: str) -> PlanAccount:
    """Resuelve la entrada del plan para `account_code` o lanza `PostingRuleError`."""
    if not isinstance(account_code, str) or not ACCOUNT_CODE_RE.match(account_code):
        raise PostingRuleError(f"código de cuenta inválido: {account_code!r}")
    prefix = account_code.split(".", 1)[0]
    plan = PLAN_DE_CUENTAS.get(prefix)
    if plan is None:
        raise PostingRuleError(f"código de cuenta fuera del plan de cuentas: {account_code!r}")
    return plan


# --------------------------------------------------------------------------- valores monetarios


def canonical_amount(value: Decimal) -> str:
    """Representación decimal canónica sin ceros a la derecha (ADR-0006)."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def parse_amount(raw: Any) -> Decimal:
    """Valida un importe de asiento: cadena decimal, finito, > 0, escala ≤ 18."""
    if isinstance(raw, (bool, float)):
        raise PostingRuleError("amount debe ser una cadena decimal; float y bool están prohibidos (ADR-0006)")
    if not isinstance(raw, (str, int, Decimal)):
        raise PostingRuleError("amount debe ser una cadena decimal")
    try:
        value = to_decimal(raw)
    except Exception as exc:  # MoneyError (ValueError) y casos límite de Decimal
        raise PostingRuleError(f"amount inválido: {raw!r}") from exc
    if not value.is_finite():
        raise PostingRuleError("amount debe ser un número finito")
    if value <= 0:
        raise PostingRuleError("amount debe ser mayor que cero")

    text = format(value, "f")
    whole, _, fraction = text.partition(".")
    if len(whole) > MAX_AMOUNT_INTEGER_DIGITS:
        raise PostingRuleError(f"amount supera los {MAX_AMOUNT_INTEGER_DIGITS} dígitos enteros permitidos")
    if len(fraction) > MAX_AMOUNT_SCALE:
        raise PostingRuleError(f"amount supera la escala de {MAX_AMOUNT_SCALE} decimales (NUMERIC(38,18))")
    return value


def normalize_direction(raw: Any) -> Literal["D", "C"]:
    """Normaliza `D|C|debit|credit` (insensible a mayúsculas) a `D|C`."""
    if not isinstance(raw, str):
        raise PostingRuleError(f"dirección inválida: {raw!r} (usa 'D' o 'C')")
    direction = _DIRECTION_ALIASES.get(raw.strip().lower())
    if direction is None:
        raise PostingRuleError(f"dirección inválida: {raw!r} (usa 'D' o 'C')")
    return direction


def _parse_uuid(value: Any, field: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise PostingRuleError(f"{field} debe ser un UUID") from exc


# --------------------------------------------------------------------------- modelo de hechos


@dataclass(frozen=True)
class EntryFact:
    """Asiento validado: posiciones 1..N, importe canónico y propietario resuelto."""

    position: int
    account_code: str
    direction: Literal["D", "C"]
    amount: Decimal
    currency: str
    owner_id: uuid.UUID
    owner_type: str
    reverses_entry_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ResolvedEntry:
    """Asiento con la cuenta ya persistida: lista para insertar y para el evento."""

    entry_id: uuid.UUID
    position: int
    account_id: uuid.UUID
    account_code: str
    direction: str
    amount: Decimal
    currency: str
    reverses_entry_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- reglas


def validate_posting_rules(
    *,
    tx_type: str,
    entries: Sequence[Mapping[str, Any]],
    reverses_tx_id: uuid.UUID | None,
) -> list[EntryFact]:
    """Valida las reglas de un posting. Devuelve los hechos con `position` 1..N.

    Reglas (L §1, §3, §7, §8):
    - `type` pertenece al catálogo de tipos de transacción;
    - ≥ 2 asientos (invariante 1: doble entrada obligatoria);
    - `amount > 0`, finito, ≤ 18 decimales y ≤ 20 dígitos enteros;
    - `currency` ISO 4217 de 3 mayúsculas;
    - Σ débitos = Σ créditos **por transacción** (invariante 1; la misma regla
      que aplica `ledger.ledger_assert_balanced` en BD, ADR-0011 §1);
    - una sola moneda salvo `conversion`/`reversal` (invariante 4);
    - `reversal` exige `reverses_tx_id`; el resto de tipos lo prohíben (L §3);
    - prefijo de cuenta en el plan de cuentas y reglas de `owner_id` (L §7.1).
    """
    if tx_type not in TX_TYPES:
        raise PostingRuleError(f"tipo de transacción inválido: {tx_type!r}")
    if len(entries) < 2:
        raise PostingRuleError("un posting requiere al menos 2 asientos (double-entry)")
    if tx_type == "reversal" and reverses_tx_id is None:
        raise PostingRuleError("type='reversal' exige reverses_tx_id (L §3)")
    if tx_type != "reversal" and reverses_tx_id is not None:
        raise PostingRuleError("solo type='reversal' admite reverses_tx_id (L §3)")

    facts: list[EntryFact] = []
    for offset, entry in enumerate(entries):
        account_code = entry.get("account_code")
        if not isinstance(account_code, str):
            raise PostingRuleError(f"account_code debe ser una cadena: {account_code!r}")
        plan = plan_for_code(account_code)
        currency = entry.get("currency")
        if not isinstance(currency, str) or not CURRENCY_RE.match(currency):
            raise PostingRuleError(f"currency inválida en {account_code!r}: {currency!r}")

        raw_owner = entry.get("owner_id")
        raw_owner_type = entry.get("owner_type")
        if plan.is_control:
            if raw_owner is not None:
                raise PostingRuleError(f"la cuenta de control {account_code!r} no admite owner_id")
            if raw_owner_type is not None and raw_owner_type != "system":
                raise PostingRuleError(f"la cuenta de control {account_code!r} no admite owner_type={raw_owner_type!r}")
            owner_id, owner_type = SYSTEM_OWNER_ID, "system"
        else:
            if raw_owner is None:
                raise PostingRuleError(f"la cuenta {account_code!r} requiere owner_id (L §7.1)")
            owner_id = _parse_uuid(raw_owner, "owner_id")
            owner_type = raw_owner_type or "user"
            if owner_type not in ("user", "tenant"):
                raise PostingRuleError(f"owner_type inválido: {owner_type!r}")

        raw_reverses_entry = entry.get("reverses_entry_id")
        reverses_entry_id = None if raw_reverses_entry is None else _parse_uuid(raw_reverses_entry, "reverses_entry_id")

        facts.append(
            EntryFact(
                position=offset + 1,
                account_code=str(account_code),
                direction=normalize_direction(entry.get("direction")),
                amount=parse_amount(entry.get("amount")),
                currency=currency,
                owner_id=owner_id,
                owner_type=owner_type,
                reverses_entry_id=reverses_entry_id,
            )
        )

    currencies = {fact.currency for fact in facts}
    if len(currencies) > 1 and tx_type not in MULTI_CURRENCY_TX_TYPES:
        raise PostingRuleError(
            f"la transacción {tx_type!r} no admite más de una moneda (invariante 4); usa type='conversion'"
        )

    debits = sum((f.amount for f in facts if f.direction == "D"), Decimal(0))
    credits = sum((f.amount for f in facts if f.direction == "C"), Decimal(0))
    if debits != credits:
        raise PostingRuleError(
            f"asientos desbalanceados: débitos {canonical_amount(debits)} != créditos {canonical_amount(credits)} "
            f"(invariante 1)"
        )

    return facts


# --------------------------------------------------------------------------- hash canónico


def canonical_request(
    *,
    tx_type: str,
    correlation_id: uuid.UUID,
    causation_id: uuid.UUID | None,
    occurred_at: datetime,
    metadata: Mapping[str, Any],
    reverses_tx_id: uuid.UUID | None,
    entries: Sequence[Mapping[str, Any]],
    subject: str,
) -> dict[str, Any]:
    """Cuerpo canónico congelado para el hash de idempotencia (ADR-0010 §1)."""
    return {
        "subject": subject,
        "type": tx_type,
        "correlation_id": str(correlation_id),
        "causation_id": str(causation_id) if causation_id else None,
        "occurred_at": occurred_at.isoformat(),
        "metadata": dict(metadata),
        "reverses_tx_id": str(reverses_tx_id) if reverses_tx_id else None,
        "entries": [
            {
                "account_code": str(entry.get("account_code")),
                "direction": normalize_direction(entry.get("direction")),
                "amount": canonical_amount(parse_amount(entry.get("amount"))),
                "currency": str(entry.get("currency")),
                "owner_id": str(entry.get("owner_id")) if entry.get("owner_id") else None,
                "owner_type": entry.get("owner_type"),
                "reverses_entry_id": str(entry.get("reverses_entry_id")) if entry.get("reverses_entry_id") else None,
            }
            for entry in entries
        ],
    }


def posting_request_hash(
    *,
    tx_type: str,
    correlation_id: uuid.UUID,
    causation_id: uuid.UUID | None,
    occurred_at: datetime,
    metadata: Mapping[str, Any],
    reverses_tx_id: uuid.UUID | None,
    entries: Sequence[Mapping[str, Any]],
    subject: str,
) -> str:
    """SHA-256 del cuerpo canónico del posting (incluye el sujeto autenticado)."""
    return request_hash(
        canonical_request(
            tx_type=tx_type,
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
            metadata=metadata,
            reverses_tx_id=reverses_tx_id,
            entries=entries,
            subject=subject,
        )
    )


def advisory_lock_key(idempotency_key: str) -> int:
    """Clave advisory de PostgreSQL (int8 con signo) para la clave de idempotencia."""
    digest = hashlib.sha256(f"ledger:idempotency:{idempotency_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


# --------------------------------------------------------------------------- evento


def build_ledger_posted_payload(
    *,
    transaction_id: uuid.UUID,
    tx_type: str,
    correlation_id: uuid.UUID,
    occurred_at: datetime,
    entries: Sequence[ResolvedEntry],
) -> dict[str, Any]:
    """Payload de `LedgerPosted` (P-event-catalog #38 y L §5)."""
    return {
        "transaction_id": str(transaction_id),
        "type": tx_type,
        "correlation_id": str(correlation_id),
        "occurred_at": occurred_at.isoformat(),
        "entries": [
            {
                "account_id": str(entry.account_id),
                "direction": entry.direction,
                "amount": canonical_amount(entry.amount),
                "currency": entry.currency,
            }
            for entry in entries
        ],
    }
