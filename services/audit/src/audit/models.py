"""models — tablas del Audit Service y garantía de inmutabilidad (append-only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from platform_kernel.clock import utcnow
from sqlalchemy import DateTime, Index, Integer, String, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from audit.db import SCHEMA, Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class AuditRecord(Base):
    __tablename__ = "records"
    __table_args__ = (
        Index("ix_records_aggregate", "aggregate_type", "aggregate_id"),
        Index("ix_records_recorded", "recorded_at"),
        Index("ix_records_action", "action"),
        {"schema": SCHEMA},
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aggregate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    actor_id: Mapped[str | None] = mapped_column(String(80))
    resource_type: Mapped[str | None] = mapped_column(String(40))
    resource_id: Mapped[str | None] = mapped_column(String(80))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    request_id: Mapped[str | None] = mapped_column(String(36))
    correlation_id: Mapped[str | None] = mapped_column(String(36))
    causation_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str | None] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def _forbid(_mapper, _connection, _state) -> None:  # type: ignore[no-untyped-def]
    raise RuntimeError("AuditRecord es append-only: UPDATE/DELETE prohibidos")


event.listen(AuditRecord, "before_update", _forbid)
event.listen(AuditRecord, "before_delete", _forbid)


__all__ = ["AuditRecord"]
