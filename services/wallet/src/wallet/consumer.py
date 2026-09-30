"""consumer - consumidor de `ledger.ledger_transaction.ledger_posted` (Q §2.5, P §3.3).

Grupo `wallet-service`: aplica cada asiento `owner_type == "user"` a la
proyección `balances` con deduplicación por `event_id` (at-least-once).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import ConsumerRecord, TopicPartition
from platform_contracts.events import LEDGER_POSTED, topic_for_event
from platform_kernel.events import EventEnvelope
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wallet.config import WalletSettings
from wallet.service import WalletService

logger = logging.getLogger("wallet.consumer")

GROUP_ID = "wallet-service"
REQUEST_TIMEOUT_MS = 5000
RETRY_DELAY_SECONDS = 5.0

LEDGER_POSTED_TOPIC = topic_for_event("ledger", "LedgerTransaction", LEDGER_POSTED)


class WalletEventConsumer:
    """Consume `LedgerPosted` y actualiza la proyección de balances."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: WalletSettings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="wallet-event-consumer")

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
            except Exception:
                logger.warning(
                    "consumidor de eventos interrumpido; se reintentará",
                    extra={"extra_fields": {"service": "wallet"}},
                )
                await self._close_consumer()
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=RETRY_DELAY_SECONDS)
            except TimeoutError:
                continue

    async def _consume(self) -> None:
        consumer = AIOKafkaConsumer(
            LEDGER_POSTED_TOPIC,
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
            # sin payload en el log: puede contener datos sensibles
            logger.error(
                "mensaje de evento inválido; se omite",
                extra={
                    "extra_fields": {"topic": message.topic, "partition": message.partition, "offset": message.offset}
                },
            )
            await consumer.commit({offset: message.offset + 1})
            return
        if envelope.event_type == LEDGER_POSTED:
            async with self._session_factory() as session:
                service = WalletService(session, self._settings)
                applied = await service.apply_ledger_posted(envelope)
            if applied:
                logger.info(
                    "balance aplicado",
                    extra={"extra_fields": {"event_id": envelope.event_id}},
                )
        await consumer.commit({offset: message.offset + 1})

    async def _close_consumer(self) -> None:
        consumer, self._consumer = self._consumer, None
        if consumer is not None:
            with contextlib.suppress(Exception):
                await consumer.stop()


__all__ = ["GROUP_ID", "LEDGER_POSTED_TOPIC", "WalletEventConsumer"]
