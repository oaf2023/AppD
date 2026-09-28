"""outbox — despachador de eventos del outbox hacia el Audit Service (ADR-0007).

Los eventos se insertan en la misma transacción que el cambio de estado; aquí
se publican de forma asíncrona con reintentos. El Audit Service deduplica por
`event_id`, por lo que los reintentos son seguros.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from platform_contracts.audit import AuditBatchIn, AuditRecordIn
from platform_kernel.security.tokens import new_service_token
from sqlalchemy import select

from identity.config import IdentitySettings
from identity.models import OutboxEvent

logger = logging.getLogger("identity.outbox")

SEVERITY_BY_EVENT = {
    "LoginFailed": "WARNING",
    "SessionRevoked": "WARNING",
    "PasswordResetCompleted": "CRITICAL",
    "MfaEnabled": "CRITICAL",
    "MfaDisabled": "CRITICAL",
}


def envelope_to_audit_record(row: OutboxEvent) -> AuditRecordIn:
    return AuditRecordIn(
        event_id=row.id,
        event_type=row.event_type,
        schema_version=row.schema_version,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        action=row.event_type,
        actor_type="user" if row.aggregate_type == "User" else "system",
        actor_id=row.aggregate_id if row.aggregate_type == "User" else None,
        resource_type=row.aggregate_type,
        resource_id=row.aggregate_id,
        correlation_id=row.correlation_id,
        request_id=row.causation_id,
        causation_id=None,
        severity=SEVERITY_BY_EVENT.get(row.event_type, "INFO"),
        payload=row.payload,
        recorded_at=row.created_at,
    )


class OutboxDispatcher:
    def __init__(self, session_factory, settings: IdentitySettings) -> None:  # type: ignore[no-untyped-def]
        self._session_factory = session_factory
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="identity-outbox-dispatcher")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task:
            self._task.cancel()
            import contextlib

            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self.dispatch_once()
            except Exception:
                logger.exception("error despachando outbox")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._settings.dispatcher_interval_seconds)
            except TimeoutError:
                continue

    async def dispatch_once(self, batch_size: int = 100) -> int:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(OutboxEvent)
                        .where(OutboxEvent.published_at.is_(None))
                        .order_by(OutboxEvent.created_at)
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )
            if not rows:
                return 0
            records = [envelope_to_audit_record(r) for r in rows]
            try:
                await self._post(records)
            except Exception as exc:
                for r in rows:
                    r.attempts += 1
                    r.last_error = str(exc)[:2000]
                await session.commit()
                raise
            from platform_kernel.clock import utcnow

            for r in rows:
                r.attempts += 1
                r.published_at = utcnow()
                r.last_error = None
            await session.commit()
            return len(rows)

    async def _post(self, records: list[AuditRecordIn]) -> None:
        token = new_service_token(
            service_name="identity",
            secret=self._settings.service_token_secret,
            issuer=self._settings.jwt_issuer,
            audience=self._settings.service_token_audience,
            ttl_seconds=300,
        )
        payload = AuditBatchIn(records=records).model_dump(mode="json")
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{self._settings.audit_service_url.rstrip('/')}/internal/v1/audit-events",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()


__all__ = ["OutboxDispatcher", "envelope_to_audit_record"]
