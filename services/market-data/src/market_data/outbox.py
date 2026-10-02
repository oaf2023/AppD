"""outbox — relay transactional outbox → Redpanda (ADR-0007, ADR-0016, BUILD-029).

Clón del relay de `accounts`/`identity` adaptado a `market-data`: cada
`SymbolUpdated` se inserta en la misma transacción que el catálogo
(`catalog.insert_suspension`) y aquí se publica con reintentos/backoff; tras
`outbox_max_attempts` va a la DLQ. Entrega at-least-once (`event_id` ida y
vuelta, P §1).

Diferencia con el resto de servicios: la fila ya persiste el **envelope
completo** en `payload` y el tópico (`market.symbols.changed`) en `topic`, así
que la serialización es directa (`json.dumps(row.payload)`) y la clave de
partición es `aggregate_id` — sin `topic_for_event`.
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
from platform_contracts.events import dlq_topic
from platform_kernel.clock import utcnow
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from market_data.config import MarketDataSettings
from market_data.metrics import BACKLOG_GAUGE, DEAD_LETTERED_COUNTER, PUBLISHED_COUNTER
from market_data.tables import OutboxRow

logger = logging.getLogger("market_data.outbox")

MAX_ERROR_LENGTH = 2000
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


def encode_payload(row: OutboxRow) -> bytes:
    """Envelope canónico (P §1) ya persistido en `payload` → bytes JSON."""
    return json.dumps(row.payload, ensure_ascii=False).encode("utf-8")


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
        settings: MarketDataSettings,
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
        self._task = asyncio.create_task(self._run(), name="market-data-outbox-relay")

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
                        select(OutboxRow)
                        .where(
                            OutboxRow.published_at.is_(None),
                            OutboxRow.dead_lettered_at.is_(None),
                            (OutboxRow.next_attempt_at.is_(None)) | (OutboxRow.next_attempt_at <= now),
                        )
                        .order_by(OutboxRow.created_at)
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
                                "event_type": row.event_type,
                                "topic": row.topic,
                                "error": str(exc)[:MAX_ERROR_LENGTH],
                            }
                        },
                    )
            await session.commit()

            backlog = await session.scalar(
                select(func.count())
                .select_from(OutboxRow)
                .where(OutboxRow.published_at.is_(None), OutboxRow.dead_lettered_at.is_(None))
            )
        BACKLOG_GAUGE.labels(settings.service_name).set(int(backlog or 0))
        if published:
            PUBLISHED_COUNTER.labels(settings.service_name).inc(published)
        if dead:
            DEAD_LETTERED_COUNTER.labels(settings.service_name).inc(dead)
        if failed:
            logger.warning("eventos del outbox requieren reintento", extra={"extra_fields": {"cantidad": failed}})
        return published

    def _record_failure(self, row: OutboxRow, exc: Exception, max_attempts: int) -> None:
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

    async def _send_event(self, row: OutboxRow) -> None:
        key = str(row.payload.get("aggregate_id", row.id))
        await self._get_sender().send(topic=row.topic, key=key.encode("utf-8"), value=encode_payload(row))

    async def _send_dlq(self, row: OutboxRow) -> None:
        key = str(row.payload.get("aggregate_id", row.id))
        body = {
            "dlq_reason": "max_attempts_exceeded",
            "original_topic": row.topic,
            "attempts": row.publish_attempts,
            "last_error": row.last_error,
            "envelope": row.payload,
        }
        await self._get_sender().send(
            topic=dlq_topic(row.topic),
            key=key.encode("utf-8"),
            value=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )


__all__ = ["EventSender", "KafkaEventSender", "OutboxRelay", "compute_backoff_ms", "encode_payload"]
