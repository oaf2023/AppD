"""consumer — consumidor de Redpanda hacia la tabla append-only de auditoría (ADR-0007).

Suscripción a los topics de la Fase 1, procesamiento secuencial y commit manual
solo tras persistir (at-least-once + dedup por `event_id` en `insert_records`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import ConsumerRecord, TopicPartition
from platform_contracts.audit import AuditRecordIn
from platform_contracts.events import PHASE1_TOPICS
from platform_kernel.events import EventEnvelope
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from audit.config import AuditSettings
from audit.ingest import insert_records

logger = logging.getLogger("audit.consumer")

GROUP_ID = "audit-service"
REQUEST_TIMEOUT_MS = 5000
RETRY_DELAY_SECONDS = 5.0
MAX_ERROR_LENGTH = 2000

SEVERITY_BY_EVENT = {
    "LoginFailed": "WARNING",
    "SessionRevoked": "WARNING",
    "PasswordResetCompleted": "CRITICAL",
    "MfaEnabled": "CRITICAL",
    "MfaDisabled": "CRITICAL",
}


def record_from_envelope(envelope: EventEnvelope) -> AuditRecordIn:
    return AuditRecordIn(
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        schema_version=envelope.schema_version,
        aggregate_type=envelope.aggregate_type,
        aggregate_id=envelope.aggregate_id,
        action=envelope.event_type,
        actor_type="user" if envelope.aggregate_type == "User" else "system",
        actor_id=envelope.aggregate_id if envelope.aggregate_type == "User" else None,
        resource_type=envelope.aggregate_type,
        resource_id=envelope.aggregate_id,
        correlation_id=envelope.correlation_id,
        request_id=envelope.causation_id,
        causation_id=None,
        severity=SEVERITY_BY_EVENT.get(envelope.event_type, "INFO"),
        payload=envelope.payload,
        recorded_at=envelope.timestamp,
    )


class AuditEventConsumer:
    """Consume los eventos Fase 1, los persiste y confirma offset a offset."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: AuditSettings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="audit-event-consumer")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._close_consumer()

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._consume()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "consumidor de eventos interrumpido; se reintentará",
                    extra={"extra_fields": {"error": str(exc)[:MAX_ERROR_LENGTH]}},
                )
                await self._close_consumer()
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=RETRY_DELAY_SECONDS)
            except TimeoutError:
                continue

    async def _consume(self) -> None:
        consumer = AIOKafkaConsumer(
            *PHASE1_TOPICS,
            bootstrap_servers=self._settings.redpanda_bootstrap_servers,
            group_id=GROUP_ID,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            request_timeout_ms=REQUEST_TIMEOUT_MS,
            client_id=f"{self._settings.service_name}-event-consumer",
        )
        self._consumer = consumer
        try:
            await consumer.start()
            while not self._stopped.is_set():
                message = await consumer.getone()
                await self._handle(consumer, message)
        finally:
            await self._close_consumer()

    async def _handle(self, consumer: AIOKafkaConsumer, message: ConsumerRecord) -> None:
        offset = TopicPartition(message.topic, message.partition)
        try:
            envelope = EventEnvelope.model_validate(json.loads(message.value))
        except Exception:
            # sin payload en el log: puede contener datos personales
            logger.error(
                "mensaje de evento inválido; se omite",
                extra={
                    "extra_fields": {"topic": message.topic, "partition": message.partition, "offset": message.offset}
                },
            )
            await consumer.commit({offset: message.offset + 1})
            return
        async with self._session_factory() as session:
            await insert_records(session, [record_from_envelope(envelope)])
        await consumer.commit({offset: message.offset + 1})

    async def _close_consumer(self) -> None:
        consumer, self._consumer = self._consumer, None
        if consumer is not None:
            with contextlib.suppress(Exception):
                await consumer.stop()


__all__ = ["SEVERITY_BY_EVENT", "AuditEventConsumer", "record_from_envelope"]
