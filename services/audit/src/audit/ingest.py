"""ingest — inserción idempotente de registros de auditoría (dedup por `event_id`)."""

from __future__ import annotations

from platform_contracts.audit import AuditRecordIn
from platform_kernel.clock import utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from audit.models import AuditRecord


async def insert_records(session: AsyncSession, records: list[AuditRecordIn]) -> tuple[int, int]:
    """Inserta los registros nuevos y hace commit; devuelve (aceptados, duplicados)."""
    event_ids = [r.event_id for r in records]
    query = select(AuditRecord.event_id).where(AuditRecord.event_id.in_(event_ids))
    existing = set((await session.execute(query)).scalars())
    accepted = 0
    duplicates = 0
    for record in records:
        if record.event_id in existing:
            duplicates += 1
            continue
        session.add(
            AuditRecord(
                event_id=record.event_id,
                event_type=record.event_type,
                schema_version=record.schema_version,
                aggregate_type=record.aggregate_type,
                aggregate_id=record.aggregate_id,
                action=record.action,
                actor_type=record.actor_type,
                actor_id=record.actor_id,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                before=record.before,
                after=record.after,
                ip=record.ip,
                user_agent=record.user_agent,
                request_id=record.request_id,
                correlation_id=record.correlation_id,
                causation_id=record.causation_id,
                reason=record.reason,
                severity=record.severity,
                payload=record.payload,
                recorded_at=record.recorded_at or utcnow(),
            )
        )
        accepted += 1
    await session.commit()
    return accepted, duplicates


__all__ = ["insert_records"]
