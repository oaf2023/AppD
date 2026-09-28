"""events — envelope canónico de eventos y helpers de outbox (ADR-0016, ADR-0007)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from platform_kernel.clock import utcnow
from platform_kernel.context import get_correlation_id, get_request_id
from platform_kernel.ids import new_uuid7


class EventEnvelope(BaseModel):
    event_id: str
    event_type: str
    schema_version: int
    aggregate_id: str
    aggregate_type: str
    timestamp: datetime
    correlation_id: str | None = None
    causation_id: str | None = None
    producer: str
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_outbox_row(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "producer": self.producer,
            "created_at": self.timestamp,
        }


def build_event(
    *,
    event_type: str,
    schema_version: int,
    aggregate_id: str,
    aggregate_type: str,
    producer: str,
    payload: dict[str, Any],
    causation_id: str | None = None,
    correlation_id: str | None = None,
    timestamp: datetime | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=str(new_uuid7()),
        event_type=event_type,
        schema_version=schema_version,
        aggregate_id=aggregate_id,
        aggregate_type=aggregate_type,
        timestamp=timestamp or utcnow(),
        correlation_id=correlation_id or get_correlation_id(),
        causation_id=causation_id or get_request_id(),
        producer=producer,
        payload=payload,
    )


__all__ = ["EventEnvelope", "build_event"]
