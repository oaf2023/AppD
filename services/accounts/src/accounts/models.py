"""models - tablas del Accounts Service (O-database-strategy §3, BUILD-020/023).

`trading_accounts`: cuenta demo/live por usuario (única parcial en demo);
`jurisdictions`: matriz versionada de jurisdicciones (gating tipado);
`outbox_events`: transactional outbox (ADR-0007).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from platform_kernel.clock import utcnow
from platform_kernel.ids import new_uuid7
from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from accounts.db import SCHEMA, Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")

ACCOUNT_TYPES = ("demo", "live")
ACCOUNT_TYPE_CHECK = f"type IN {ACCOUNT_TYPES}"
ACCOUNT_STATUSES = ("active", "suspended", "closed")
ACCOUNT_STATUS_CHECK = f"status IN {ACCOUNT_STATUSES}"
JURISDICTION_STATUSES = ("allowed", "blocked")
JURISDICTION_STATUS_CHECK = f"status IN {JURISDICTION_STATUSES}"


class TradingAccount(Base):
    """Cuenta de trading. Cierre vía `closed_at` + `status` (F2.3); sin hard delete."""

    __tablename__ = "trading_accounts"
    __table_args__ = (
        CheckConstraint(ACCOUNT_TYPE_CHECK, name="chk_account_type"),
        CheckConstraint(ACCOUNT_STATUS_CHECK, name="chk_account_status"),
        CheckConstraint("length(currency) = 3", name="chk_account_currency"),
        # O §3: idx_ta_user (user_id) WHERE status='active'
        Index(
            "ix_trading_accounts_user_active",
            "user_id",
            postgresql_where=text("status = 'active'"),
        ),
        # BUILD-020: una sola cuenta demo por usuario
        Index(
            "uq_trading_accounts_demo_user",
            "user_id",
            unique=True,
            postgresql_where=text("type = 'demo'"),
        ),
        Index("ix_trading_accounts_created", "created_at", "id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    type: Mapped[str] = mapped_column(String(8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active", server_default="active")
    alias: Mapped[str | None] = mapped_column(String(64))
    #: Pendiente de la matriz producto-jurisdiccion (BUILD-037, F4); null en F2.
    leverage: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Jurisdiction(Base):
    """Matriz de jurisdicciones versionada (BUILD-023): `allowed`/`blocked` por código."""

    __tablename__ = "jurisdictions"
    __table_args__ = (
        CheckConstraint(JURISDICTION_STATUS_CHECK, name="chk_jurisdiction_status"),
        CheckConstraint("policy_version > 0", name="chk_jurisdiction_policy_version"),
        {"schema": SCHEMA},
    )

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="allowed", server_default="allowed")
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class OutboxEvent(Base):
    """Transactional outbox: se escribe en la misma transacción que la cuenta."""

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
    producer: Mapped[str] = mapped_column(String(40), nullable=False, default="accounts")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


__all__ = [
    "ACCOUNT_STATUSES",
    "ACCOUNT_STATUS_CHECK",
    "ACCOUNT_TYPES",
    "ACCOUNT_TYPE_CHECK",
    "JSON_TYPE",
    "JURISDICTION_STATUSES",
    "JURISDICTION_STATUS_CHECK",
    "Jurisdiction",
    "OutboxEvent",
    "TradingAccount",
]
