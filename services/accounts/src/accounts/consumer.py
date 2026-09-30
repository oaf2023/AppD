"""consumer — auto-provisión de la cuenta demo desde `identity.user.registered` (BUILD-020).

Suscripción al evento de registro, procesamiento secuencial y commit manual solo
tras persistir (at-least-once); la unicidad de la cuenta demo (índice parcial)
hace el handler idempotente ante reentregas.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import ConsumerRecord, TopicPartition
from platform_contracts.events import USER_REGISTERED, topic_for_event
from platform_kernel.errors import ConflictError
from platform_kernel.events import EventEnvelope
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from accounts.config import AccountsSettings
from accounts.service import AccountsService

logger = logging.getLogger("accounts.consumer")

GROUP_ID = "accounts-service"
REQUEST_TIMEOUT_MS = 5000
RETRY_DELAY_SECONDS = 5.0
MAX_ERROR_LENGTH = 2000

USER_REGISTERED_TOPIC = topic_for_event("identity", "User", USER_REGISTERED)


async def provision_demo_from_event(
    session: AsyncSession,
    settings: AccountsSettings,
    envelope: EventEnvelope,
) -> bool:
    """Crea la cuenta demo del usuario registrado; devuelve False si ya existía.

    La jurisdicción viene del propio evento (origen único: registro en identity).
    Un payload inválido se omite (commit + log) para no bloquear el topic.
    """
    service = AccountsService(session, settings)
    try:
        user_id = uuid.UUID(str(envelope.payload["user_id"]))
        jurisdiction = str(envelope.payload["jurisdiction"])
    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "payload UserRegistered inválido; se omite la auto-provisión",
            extra={"extra_fields": {"event_id": envelope.event_id, "error": str(exc)[:MAX_ERROR_LENGTH]}},
        )
        await session.rollback()
        return False
    if await service.get_demo_account(user_id) is not None:
        return False
    try:
        await service.create_account(
            user_id=user_id,
            mode="demo",
            currency=settings.demo_currency,
            jurisdiction=jurisdiction,
            causation_id=envelope.event_id,
            correlation_id=envelope.correlation_id,
        )
    except ConflictError:
        # reentrega concurrente: la unicidad del índice ya garantizó una sola cuenta
        await session.rollback()
        return False
    return True


class AccountsEventConsumer:
    """Consume `identity.user.registered`, auto-provisiona la demo y confirma offset."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: AccountsSettings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="accounts-event-consumer")

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
            USER_REGISTERED_TOPIC,
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
        if envelope.event_type == USER_REGISTERED:
            async with self._session_factory() as session:
                created = await provision_demo_from_event(session, self._settings, envelope)
            if created:
                logger.info(
                    "cuenta demo auto-provisionada",
                    extra={"extra_fields": {"event_id": envelope.event_id}},
                )
        await consumer.commit({offset: message.offset + 1})

    async def _close_consumer(self) -> None:
        consumer, self._consumer = self._consumer, None
        if consumer is not None:
            with contextlib.suppress(Exception):
                await consumer.stop()


__all__ = ["GROUP_ID", "USER_REGISTERED_TOPIC", "AccountsEventConsumer", "provision_demo_from_event"]
