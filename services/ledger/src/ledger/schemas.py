"""schemas — contratos HTTP del Ledger Service (API-first, ADR-0004).

El dinero viaja siempre como cadena decimal (ADR-0006): un número JSON se
rechaza con `422` para impedir cualquier paso por `float`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TxType = Literal[
    "deposit",
    "withdrawal",
    "transfer",
    "conversion",
    "fee",
    "swap",
    "pnl",
    "margin_funding",
    "reversal",
    "adjustment",
]


class EntryIn(BaseModel):
    """Asiento individual de un posting."""

    model_config = ConfigDict(extra="forbid")

    account_code: str = Field(min_length=6, max_length=64, examples=["2000.PAYABLE.CLIENT.USD.u1"])
    direction: str = Field(
        min_length=1,
        max_length=8,
        description="D o C (también debit/credit, insensible a mayúsculas). Se normaliza a D|C.",
        examples=["D"],
    )
    amount: str = Field(description="Importe decimal en cadena; nunca un número JSON (ADR-0006)")
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$", examples=["USD"])
    owner_id: uuid.UUID | None = Field(default=None, description="Obligatorio en cuentas no control (L §7.1)")
    owner_type: Literal["user", "tenant"] | None = None
    reverses_entry_id: uuid.UUID | None = Field(default=None, description="Reversión granular (L §3)")


class PostingsIn(BaseModel):
    """Comando de escritura: única vía de creación de asientos (Q-api-map §3)."""

    model_config = ConfigDict(extra="forbid")

    type: TxType
    correlation_id: uuid.UUID
    causation_id: uuid.UUID | None = None
    occurred_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    reverses_tx_id: uuid.UUID | None = None
    entries: list[EntryIn] = Field(min_length=2, max_length=1000)

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class EntryOut(BaseModel):
    """Asiento persistido."""

    entry_id: uuid.UUID
    position: int
    account_id: uuid.UUID
    account_code: str
    direction: Literal["D", "C"]
    amount: str
    currency: str
    reverses_entry_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    owner_type: str | None = None


class PostingOut(BaseModel):
    """Transacción ledger con sus asientos (respuesta de creación y de replay)."""

    transaction_id: uuid.UUID
    type: TxType
    correlation_id: uuid.UUID
    causation_id: uuid.UUID | None = None
    occurred_at: datetime
    reverses_tx_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    entries: list[EntryOut]
    created_at: datetime


class HealthOut(BaseModel):
    service: str
    status: str


class ReadyOut(BaseModel):
    status: str


# --------------------------------------------------------------- balances internos (§3)


class OwnerBalance(BaseModel):
    """Saldo de un propietario en una moneda (créditos - débitos, L §4.1)."""

    owner_id: uuid.UUID
    currency: str
    balance: str


class OwnerBalancesOut(BaseModel):
    data: list[OwnerBalance]
    as_of: datetime


# ------------------------------------------------- superficie pública (Q-api-map §2.6)


class PageInfo(BaseModel):
    """Q-api-map §1.4: cursor opaco, sin offset."""

    next_cursor: str | None = None
    prev_cursor: str | None = None
    has_more: bool = False
    limit: int = 25


class PublicEntryOut(BaseModel):
    """Asiento propio con el contexto de su transacción (extractos y listados)."""

    entry_id: uuid.UUID
    transaction_id: uuid.UUID
    account_id: uuid.UUID
    account_code: str
    direction: Literal["D", "C"]
    amount: str
    currency: str
    tx_type: TxType
    occurred_at: datetime
    created_at: datetime


class EntryPageOut(BaseModel):
    data: list[PublicEntryOut]
    page: PageInfo


class StatementPeriod(BaseModel):
    period_from: datetime = Field(serialization_alias="from")
    period_to: datetime = Field(serialization_alias="to")


class StatementSummaryOut(BaseModel):
    statement_id: str
    period: StatementPeriod
    currency: str
    opening_balance: str
    closing_balance: str
    entries_count: int


class StatementPageOut(BaseModel):
    data: list[StatementSummaryOut]
    page: PageInfo


class StatementOut(StatementSummaryOut):
    entries: list[PublicEntryOut]
    page: PageInfo
    as_of: datetime


__all__ = [
    "EntryIn",
    "EntryOut",
    "EntryPageOut",
    "HealthOut",
    "OwnerBalance",
    "OwnerBalancesOut",
    "PageInfo",
    "PostingOut",
    "PostingsIn",
    "PublicEntryOut",
    "ReadyOut",
    "StatementOut",
    "StatementPageOut",
    "StatementPeriod",
    "StatementSummaryOut",
    "TxType",
]
