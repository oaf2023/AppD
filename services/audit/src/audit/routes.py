"""routes — endpoints del Audit Service."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from platform_contracts.audit import AuditBatchIn, AuditBatchOut, AuditPage, AuditRecordOut
from platform_contracts.roles import BACKOFFICE_ROLES
from platform_kernel.auth import require_roles, require_service
from platform_kernel.errors import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from audit.config import AuditSettings, get_audit_settings
from audit.db import get_session
from audit.ingest import insert_records
from audit.models import AuditRecord

router = APIRouter()

SettingsDep = Annotated[AuditSettings, Depends(get_audit_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _encode_cursor(recorded_at: datetime, event_id: str) -> str:
    raw = f"{recorded_at.isoformat()}|{event_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        ts_raw, _, event_id = base64.urlsafe_b64decode(padded.encode()).decode().partition("|")
        return datetime.fromisoformat(ts_raw), event_id
    except (ValueError, binascii.Error) as exc:
        raise ValidationError("cursor inválido") from exc


@router.get("/healthz", tags=["system"])
async def healthz() -> dict[str, str]:
    return {"service": "audit", "status": "ok"}


@router.get("/readyz", tags=["system"])
async def readyz(session: SessionDep) -> dict[str, str]:
    from sqlalchemy import text

    await session.execute(text("SELECT 1"))
    return {"status": "ready"}


@router.post("/internal/v1/audit-events", response_model=AuditBatchOut, tags=["internal"])
async def ingest(
    body: AuditBatchIn,
    session: SessionDep,
    service: Annotated[str, Depends(require_service)],
) -> AuditBatchOut:
    """Ingesta idempotente por `event_id` (solo servicios autenticados)."""
    accepted, duplicates = await insert_records(session, body.records)
    return AuditBatchOut(accepted=accepted, duplicates=duplicates)


@router.get("/api/v1/audit-events", response_model=AuditPage, tags=["audit"])
async def list_records(
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[object, Depends(require_roles(*BACKOFFICE_ROLES))],
    action: str | None = None,
    event_type: str | None = None,
    aggregate_id: str | None = None,
    severity: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditPage:
    query = select(AuditRecord).order_by(AuditRecord.recorded_at.desc(), AuditRecord.event_id.desc())
    if action:
        query = query.where(AuditRecord.action == action)
    if event_type:
        query = query.where(AuditRecord.event_type == event_type)
    if aggregate_id:
        query = query.where(AuditRecord.aggregate_id == aggregate_id)
    if severity:
        query = query.where(AuditRecord.severity == severity)
    if date_from:
        query = query.where(AuditRecord.recorded_at >= date_from)
    if date_to:
        query = query.where(AuditRecord.recorded_at <= date_to)
    if cursor:
        ts, event_id = _decode_cursor(cursor)
        query = query.where(
            (AuditRecord.recorded_at < ts) | ((AuditRecord.recorded_at == ts) & (AuditRecord.event_id < event_id))
        )
    query = query.limit(limit + 1)
    rows = list((await session.execute(query)).scalars())
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode_cursor(rows[-1].recorded_at, rows[-1].event_id) if has_more and rows else None
    return AuditPage(items=[AuditRecordOut.model_validate(r) for r in rows], next_cursor=next_cursor)


__all__ = ["router"]
