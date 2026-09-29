"""models - tablas del Ledger Service e inmutabilidad (append-only).

Modelo fiel a `docs/phase0/L-ledger-architecture.md` §2.1/§2.2/§2.3 y ADR-0011.
Las garantías de inmutabilidad se instalan en la migración (trigger + REVOKE)
y aquí se duplican como red de seguridad a nivel de aplicación.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from platform_kernel.clock import utcnow
from platform_kernel.ids import new_uuid7
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from ledger.db import SCHEMA, Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")

ACCOUNT_CODE_PATTERN = r"^[0-9]{4}\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$"
ACCOUNT_CODE_CHECK = f"code ~ '{ACCOUNT_CODE_PATTERN}'"
ACCOUNT_TYPES = ("asset", "liability", "equity", "revenue", "expense")
ACCOUNT_TYPE_CHECK = f"type IN {ACCOUNT_TYPES}"
OWNER_TYPES = ("user", "tenant", "system")
TX_TYPES = (
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
)
TX_TYPE_CHECK = f"type IN {TX_TYPES}"
ENTRY_DIRECTIONS = ("D", "C")
AMOUNT_SCALE = 18


class LedgerAccount(Base):
    """Cuenta contable. Cierre de cuentas inactivas vía `closed_at` (L §3)."""

    __tablename__ = "ledger_accounts"
    __table_args__ = (
        CheckConstraint(ACCOUNT_CODE_CHECK, name="chk_code_format"),
        CheckConstraint("length(currency) = 3", name="chk_account_currency"),
        CheckConstraint(ACCOUNT_TYPE_CHECK, name="chk_account_type"),
        CheckConstraint("owner_type IN ('user','tenant','system')", name="chk_owner_type"),
        UniqueConstraint("code"),
        Index("ix_ledger_accounts_owner", "owner_id", "owner_type", "currency"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(16), nullable=False, server_default="system")
    is_control: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LedgerBalanceSnapshot(Base):
    """Snapshot diario de reconciliación ledger ↔ proyección (L §4.2)."""

    __tablename__ = "ledger_balance_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["account_id"],
            [f"{SCHEMA}.ledger_accounts.id"],
            name="fk_balance_snapshot_account",
        ),
        UniqueConstraint("account_id", "snapshot_date", name="uq_balance_snapshot"),
        Index("ix_ledger_balance_snapshots_date", "snapshot_date"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    ledger_balance: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class LedgerTransaction(Base):
    """Transacción financiera: agrupa asientos que cuadran entre sí (L §1)."""

    __tablename__ = "ledger_transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["reverses_tx_id"],
            [f"{SCHEMA}.ledger_transactions.id"],
            name="fk_ledger_transactions_reverses",
        ),
        CheckConstraint(TX_TYPE_CHECK, name="chk_tx_type"),
        Index("ix_ledger_transactions_occurred", "occurred_at"),
        Index("ix_ledger_transactions_correlation", "correlation_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tx_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_TYPE, nullable=False, default=dict)
    reverses_tx_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class LedgerEntry(Base):
    """Asiento individual. `amount` siempre positivo; el signo es `direction`."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transaction_id"],
            [f"{SCHEMA}.ledger_transactions.id"],
            name="fk_ledger_entries_transaction",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["account_id"],
            [f"{SCHEMA}.ledger_accounts.id"],
            name="fk_ledger_entries_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reverses_entry_id"],
            [f"{SCHEMA}.ledger_entries.id"],
            name="fk_ledger_entries_reverses",
        ),
        CheckConstraint("amount > 0", name="chk_entry_amount_positive"),
        CheckConstraint("direction IN ('D','C')", name="chk_entry_direction"),
        CheckConstraint("length(currency) = 3", name="chk_entry_currency"),
        UniqueConstraint("transaction_id", "position", name="uq_tx_position"),
        Index("ix_ledger_entries_account_id", "account_id", "id"),
        Index("ix_ledger_entries_account_created", "account_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    direction: Mapped[str] = mapped_column(String(1), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(38, AMOUNT_SCALE))
    reverses_entry_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    # relationship obligatoria: sin ella el unit-of-work no ordena el INSERT de
    # transactions antes que entries (unitofwork.py: `_dependency_processors`).
    transaction: Mapped[LedgerTransaction] = relationship()


class LedgerIdempotencyKey(Base):
    """Clave `Idempotency-Key` con la respuesta almacenada (ADR-0010, L §6).

    `response` admite NULL solo como estado transitorio de una clave reclamada
    sin respuesta; en un commit exitoso siempre está completa.
    """

    __tablename__ = "ledger_idempotency_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transaction_id"],
            [f"{SCHEMA}.ledger_transactions.id"],
            name="fk_ledger_idempotency_transaction",
        ),
        Index("ix_ledger_idempotency_expires", "expires_at"),
        {"schema": SCHEMA},
    )

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=201)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class OutboxEvent(Base):
    """Transactional outbox: se escribe en la misma transacción que los asientos."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id"),
        Index("ix_outbox_unpublished", "published_at", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aggregate_id: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(36))
    causation_id: Mapped[str | None] = mapped_column(String(36))
    producer: Mapped[str] = mapped_column(String(40), nullable=False, default="ledger")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


def _forbid(_mapper, _connection, _state) -> None:  # type: ignore[no-untyped-def]
    raise RuntimeError("ledger es append-only: UPDATE/DELETE prohibidos")


event.listen(LedgerTransaction, "before_update", _forbid)
event.listen(LedgerTransaction, "before_delete", _forbid)
event.listen(LedgerEntry, "before_update", _forbid)
event.listen(LedgerEntry, "before_delete", _forbid)

__all__ = [
    "ACCOUNT_CODE_CHECK",
    "ACCOUNT_CODE_PATTERN",
    "ACCOUNT_TYPES",
    "ACCOUNT_TYPE_CHECK",
    "AMOUNT_SCALE",
    "ENTRY_DIRECTIONS",
    "JSON_TYPE",
    "OWNER_TYPES",
    "TX_TYPES",
    "TX_TYPE_CHECK",
    "LedgerAccount",
    "LedgerBalanceSnapshot",
    "LedgerEntry",
    "LedgerIdempotencyKey",
    "LedgerTransaction",
    "OutboxEvent",
]
