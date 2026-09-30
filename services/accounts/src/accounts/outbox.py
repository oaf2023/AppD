"""outbox — relay transactional outbox → Redpanda (ADR-0007, ADR-0016).

Clon del relay de `identity` adaptado a `accounts`: cada `AccountCreated` y
`DemoAccountCreated` se inserta en la misma transacción que la cuenta y aquí se
publica con reintentos/backoff; tras `outbox_max_attempts` va a la DLQ.
Entrega at-least-once (§8: `event_id` ida y vuelta).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
from collections.abc import Callable
from datetime import timedelta
from typing import Protocol

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError, KafkaTimeoutError, NoBrokersAvailable
from platform_contracts.events import dlq_topic, topic_for_event
from platform_kernel.clock import utcnow
from platform_kernel.events import EventEnvelope
from prometheus_client import Counter, Gauge
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from accounts.config import AccountsSettings
from accounts.metrics import _shared_metric
from accounts.models import OutboxEvent

logger = logging.getLogger("accounts.outbox")

MAX_ERROR_LENGTH = 2000
# `identity.outbox` registra primero estos colectores en el mismo proceso de tests:
# aquí se reutilizan (ver `accounts.metrics._shared_metric`).
BACKLOG_GAUGE: Gauge = _shared_metric(
    Gauge,
    "platform_outbox_backlog",
    "Eventos del outbox pendientes de publicar o enviar a la DLQ",
    ["service"],
)
PUBLISHED_COUNTER: Counter = _shared_metric(
    Counter,
    "platform_outbox_published_total",
    "Eventos del outbox publicados en Redpanda",
    ["service"],
)
DEAD_LETTERED_COUNTER: Counter = _shared_metric(
    Counter,
    "platform_outbox_dead_lettered_total",
    "Eventos del outbox enviados a la DLQ",
    ["service"],
)

CONNECTION_ERRORS = (KafkaConnectionError, KafkaTimeoutError, NoBrokersAvailable)
_RNG = random.Random()


def compute_backoff_ms(
    attempt: int,
    *,
    base_ms: int,
    max_ms: int = 60_000,
    jitter: float = 0.25,
    rng: random.Random | None = None,
) -> int:
    """Backoff exponencial acotado con jitter proporcional."""
    exponent = min(max(attempt - 1, 0), 20)
    delay_ms = min(max_ms, base_ms * (2**exponent))
    factor = 1 + (_RNG if rng is None else rng).uniform(-jitter, jitter)
    return max(1, int(delay_ms * factor))


def encode_envelope(row: OutboxEvent) -> bytes:
    """Serializa la fila como envelope canónico JSON."""
    envelope = EventEnvelope(
        event_id=row.id,
        event_type=row.event_type,
        schema_version=row.schema_version,
        aggregate_id=row.aggregate_id,
        aggregate_type=row.aggregate_type,
        timestamp=row.created_at,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        producer=row.producer,
        payload=row.payload,
    )
    return envelope.model_dump_json().encode("utf-8")


class EventSender(Protocol):
    """Destino de publicación (en tests se sustituye por un doble en memoria)."""

    async def send(self, *, topic: str, key: bytes | None, value: bytes) -> None: ...

    async def close(self) -> None: ...


class KafkaEventSender:
    """Productor aiokafka (`acks=all`) con arranque perezoso y no reutilizable tras `close`."""

    def __init__(self, bootstrap_servers: str, *, request_timeout_ms: int = 5000) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            acks="all",
            request_timeout_ms=request_timeout_ms,
        )
        self._started = False

    async def send(self, *, topic: str, key: bytes | None, value: bytes) -> None:
        if not self._started:
            await self._producer.start()
            self._started = True
        await self._producer.send_and_wait(topic, key=key, value=value)

    async def close(self) -> None:
        self._started = False
        with contextlib.suppress(Exception):
            await self._producer.stop()


class OutboxRelay:
    """Publica el outbox pendiente en Redpanda y gestiona reintentos/DLQ."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: AccountsSettings,
        *,
        sender_factory: Callable[[], EventSender] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._sender_factory = sender_factory or (lambda: KafkaEventSender(settings.redpanda_bootstrap_servers))
        self._sender: EventSender | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="accounts-outbox-relay")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._dispose_sender()

    async def _run(self) -> None:
        interval_s = self._settings.outbox_relay_interval_ms / 1000
        while not self._stopped.is_set():
            try:
                await self.relay_once()
            except Exception:
                logger.exception("ciclo del relay outbox falló")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=interval_s)
            except TimeoutError:
                continue

    async def relay_once(self) -> int:
        """Publica el batch vencido en una sola pasada; devuelve los publicados."""
        settings = self._settings
        max_attempts = settings.outbox_max_attempts
        now = utcnow()
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(OutboxEvent)
                        .where(
                            OutboxEvent.published_at.is_(None),
                            OutboxEvent.dead_lettered_at.is_(None),
                            (OutboxEvent.next_attempt_at.is_(None)) | (OutboxEvent.next_attempt_at <= now),
                        )
                        .order_by(OutboxEvent.created_at)
                        .limit(settings.outbox_batch_size)
                    )
                ).scalars()
            )

            published = 0
            dead = 0
            failed = 0
            connection_error: Exception | None = None
            for row in rows:
                if connection_error is not None:
                    # cortocircuito: no reintentar contra un broker que acaba de fallar
                    self._record_failure(row, connection_error, max_attempts)
                    failed += 1
                    continue
                try:
                    if row.publish_attempts >= max_attempts:
                        await self._send_dlq(row)
                        row.dead_lettered_at = utcnow()
                        dead += 1
                    else:
                        await self._send_event(row)
                        row.published_at = utcnow()
                        row.last_error = None
                        published += 1
                except Exception as exc:
                    if isinstance(exc, CONNECTION_ERRORS):
                        connection_error = exc
                        await self._dispose_sender()
                    self._record_failure(row, exc, max_attempts)
                    failed += 1
                    logger.warning(
                        "publicación del outbox fallida",
                        extra={
                            "extra_fields": {
                                "event_id": row.id,
                                "event_type": row.event_type,
                                "error": str(exc)[:MAX_ERROR_LENGTH],
                            }
                        },
                    )
            await session.commit()

            backlog = await session.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None), OutboxEvent.dead_lettered_at.is_(None))
            )
        BACKLOG_GAUGE.labels(settings.service_name).set(int(backlog or 0))
        if published:
            PUBLISHED_COUNTER.labels(settings.service_name).inc(published)
        if dead:
            DEAD_LETTERED_COUNTER.labels(settings.service_name).inc(dead)
        if failed:
            logger.warning("eventos del outbox requieren reintento", extra={"extra_fields": {"cantidad": failed}})
        return published

    def _record_failure(self, row: OutboxEvent, exc: Exception, max_attempts: int) -> None:
        row.publish_attempts += 1
        row.last_error = str(exc)[:MAX_ERROR_LENGTH]
        if row.publish_attempts == max_attempts:
            row.next_attempt_at = None  # al ciclo siguiente intenta la DLQ
        else:
            delay_ms = compute_backoff_ms(row.publish_attempts, base_ms=self._settings.outbox_relay_interval_ms)
            row.next_attempt_at = utcnow() + timedelta(milliseconds=delay_ms)

    def _get_sender(self) -> EventSender:
        if self._sender is None:
            self._sender = self._sender_factory()
        return self._sender

    async def _dispose_sender(self) -> None:
        sender, self._sender = self._sender, None
        if sender is not None:
            with contextlib.suppress(Exception):
                await sender.close()

    async def _send_event(self, row: OutboxEvent) -> None:
        topic = topic_for_event(row.producer, row.aggregate_type, row.event_type)
        await self._get_sender().send(topic=topic, key=row.aggregate_id.encode("utf-8"), value=encode_envelope(row))

    async def _send_dlq(self, row: OutboxEvent) -> None:
        original_topic = topic_for_event(row.producer, row.aggregate_type, row.event_type)
        body = {
            "dlq_reason": "max_attempts_exceeded",
            "original_topic": original_topic,
            "attempts": row.publish_attempts,
            "last_error": row.last_error,
            "envelope": json.loads(encode_envelope(row).decode("utf-8")),
        }
        await self._get_sender().send(
            topic=dlq_topic(original_topic),
            key=row.aggregate_id.encode("utf-8"),
            value=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )


__all__ = ["EventSender", "KafkaEventSender", "OutboxRelay", "compute_backoff_ms", "encode_envelope"]
