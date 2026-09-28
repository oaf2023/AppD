"""audit — contrato del registro de auditoría (append-only) del servicio audit."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditRecordIn(BaseModel):
    event_id: str
    event_type: str
    schema_version: int = 1
    aggregate_type: str
    aggregate_id: str
    action: str
    actor_type: str = "system"  # user | service | system
    actor_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    reason: str | None = None
    severity: str = "INFO"  # INFO | WARNING | CRITICAL
    payload: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime | None = None


class AuditBatchIn(BaseModel):
    records: list[AuditRecordIn] = Field(min_length=1, max_length=200)


class AuditBatchOut(BaseModel):
    accepted: int
    duplicates: int


class AuditRecordOut(BaseModel):
    event_id: str
    event_type: str
    action: str
    aggregate_type: str
    aggregate_id: str
    actor_type: str
    actor_id: str | None
    resource_type: str | None
    resource_id: str | None
    severity: str
    correlation_id: str | None
    request_id: str | None
    recorded_at: datetime

    model_config = {"from_attributes": True}


class AuditPage(BaseModel):
    items: list[AuditRecordOut]
    next_cursor: str | None = None


__all__ = [
    "AuditBatchIn",
    "AuditBatchOut",
    "AuditPage",
    "AuditRecordIn",
    "AuditRecordOut",
]
