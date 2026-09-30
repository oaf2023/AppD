"""models - tablas del Wallet Service (O-database-strategy §2/§5.2/§9, L §4.1).

`balances` es la proyección de estado por usuario+moneda; `balance_movements` el
historial de deltas aplicados; `processed_events` la deduplicación de consumidor
(P-event-catalog §3.3); `balance_snapshots` la trazabilidad del reconciliador
ledger↔wallet (BUILD-019); `currency_config` y `conversion_rates` las tablas de
referencia previstas para Fase 2.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from platform_kernel.clock import utcnow
from platform_kernel.ids import new_uuid7
from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from wallet.db import SCHEMA, Base

AMOUNT_SCALE = 18
MOVEMENT_TX_TYPES = ("deposit", "withdrawal", "transfer", "conversion", "fee", "swap", "pnl", "adjustment")


class Balance(Base):
    """Balance disponible/reservado por usuario y moneda (proyección de `LedgerPosted`)."""

    __tablename__ = "balances"
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="chk_balance_currency"),
        CheckConstraint("reserved >= 0", name="chk_balance_reserved_non_negative"),
        UniqueConstraint("user_id", "currency", name="uq_balances_user_currency"),
        # O §5.2: idx_bal_user_curr (user_id, currency); sin `deleted_at` en F2 (ver migración)
        Index("idx_bal_user_curr", "user_id", "currency"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    available: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False, default=Decimal(0))
    reserved: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False, default=Decimal(0))
    #: true mientras el reconciliador detecta descuadre contra ledger (BUILD-019)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class BalanceMovement(Base):
    """Movimiento de saldo: un asiento propio de `LedgerPosted` aplicado a la proyección."""

    __tablename__ = "balance_movements"
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="chk_movement_currency"),
        CheckConstraint("direction IN ('D','C')", name="chk_movement_direction"),
        CheckConstraint("delta <> 0", name="chk_movement_delta_nonzero"),
        # BUILD-022: cursor `(created_at DESC, id DESC)` por usuario
        Index("ix_balance_movements_user_time", "user_id", "created_at", "id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    #: con signo: positivo = crédito (sube el balance), negativo = débito
    delta: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    direction: Mapped[str] = mapped_column(String(1), nullable=False)
    tx_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ledger_transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ProcessedEvent(Base):
    """Deduplicación de consumidor (P-event-catalog §3.3): un `event_id` = una aplicación."""

    __tablename__ = "processed_events"
    __table_args__ = ({"schema": SCHEMA},)

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class BalanceSnapshot(Base):
    """Comparación wallet↔ledger en cada pasada del reconciliador (BUILD-019)."""

    __tablename__ = "balance_snapshots"
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="chk_snapshot_currency"),
        Index("ix_balance_snapshots_checked", "checked_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    wallet_balance: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    ledger_balance: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class CurrencyConfig(Base):
    """Configuración de moneda (O §2; semilla ISO 4217 de USD en la migración)."""

    __tablename__ = "currency_config"
    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="chk_currency_config_code"),
        CheckConstraint("decimals >= 0", name="chk_currency_config_decimals"),
        {"schema": SCHEMA},
    )

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    decimals: Mapped[int] = mapped_column(nullable=False, default=2)
    symbol: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ConversionRate(Base):
    """Tasa de conversión vigente (O §2). Vacía en F2: el motor FX está en §10 como NO DETERMINADO."""

    __tablename__ = "conversion_rates"
    __table_args__ = (
        CheckConstraint("length(base) = 3", name="chk_rate_base"),
        CheckConstraint("length(quote) = 3", name="chk_rate_quote"),
        CheckConstraint("rate > 0", name="chk_rate_positive"),
        {"schema": SCHEMA},
    )

    base: Mapped[str] = mapped_column(String(3), primary_key=True)
    quote: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


__all__ = [
    "AMOUNT_SCALE",
    "MOVEMENT_TX_TYPES",
    "Balance",
    "BalanceMovement",
    "BalanceSnapshot",
    "ConversionRate",
    "CurrencyConfig",
    "ProcessedEvent",
]
