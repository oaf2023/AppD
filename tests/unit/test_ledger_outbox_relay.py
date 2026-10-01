"""Pruebas unitarias del relay transactional outbox del Ledger (SQLite en memoria).

Espejo de `tests/unit/test_outbox_relay.py` (identity): el relay de `ledger.outbox`
es un clon adaptado (ADR-0007/ADR-0016) y aquí se cubre su ciclo completo —
publicación, reintentos/backoff, cortocircuito de conexión, DLQ y `KafkaEventSender`.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from ledger.config import LedgerSettings
from ledger.db import Base
from ledger.models import OutboxEvent
from ledger.outbox import EventSender, KafkaEventSender, OutboxRelay, compute_backoff_ms
from platform_contracts.events import dlq_topic, topic_for_event
from platform_kernel.clock import utcnow
from prometheus_client import REGISTRY
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

LEDGER_POSTED_TOPIC = topic_for_event("ledger", "LedgerTransaction", "LedgerPosted")


class FakeSender(EventSender):
    """Doble en memoria que falla con las excepciones configuradas."""

    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.calls: list[tuple[str, bytes | None, bytes]] = []
        self.attempts = 0
        self.closed = False
        self._failures = list(failures or [])

    async def send(self, *, topic: str, key: bytes | None, value: bytes) -> None:
        self.attempts += 1
        if self._failures:
            raise self._failures.pop(0)
        self.calls.append((topic, key, value))

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
async def env() -> tuple[async_sessionmaker[AsyncSession], LedgerSettings]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.execute(text("ATTACH DATABASE ':memory:' AS ledger"))
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=[OutboxEvent.__table__]))
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    yield factory, LedgerSettings(outbox_relay_interval_ms=50)
    await engine.dispose()


async def _insert_row(
    factory: async_sessionmaker[AsyncSession],
    *,
    event_type: str = "LedgerPosted",
    aggregate_type: str = "LedgerTransaction",
    aggregate_id: str | None = None,
    payload: dict[str, Any] | None = None,
    **extra: Any,
) -> str:
    row = OutboxEvent(
        id=str(uuid.uuid4()),
        event_type=event_type,
        schema_version=1,
        aggregate_id=aggregate_id or str(uuid.uuid4()),
        aggregate_type=aggregate_type,
        payload=payload if payload is not None else {"demo": True},
        producer="ledger",
        created_at=utcnow(),
        **extra,
    )
    async with factory() as session:
        session.add(row)
        await session.commit()
    return row.id


async def _get_row(factory: async_sessionmaker[AsyncSession], row_id: str) -> OutboxEvent:
    async with factory() as session:
        row = (await session.execute(select(OutboxEvent).where(OutboxEvent.id == row_id))).scalars().one()
        return row


async def _clear_next_attempt(factory: async_sessionmaker[AsyncSession], row_id: str) -> None:
    async with factory() as session:
        row = (await session.execute(select(OutboxEvent).where(OutboxEvent.id == row_id))).scalars().one()
        row.next_attempt_at = None
        await session.commit()


def _aware(value: datetime | None) -> datetime | None:
    """SQLite devuelve datetimes sin tz; en las pruebas son UTC."""
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


# --------------------------------------------------------------------------- flujo


async def test_publica_el_evento_y_marca_la_fila_como_publicada(env) -> None:
    factory, settings = env
    sender = FakeSender()
    aggregate_id = str(uuid.uuid4())
    row_id = await _insert_row(factory, aggregate_id=aggregate_id, payload={"amount": "10"})
    relay = OutboxRelay(factory, settings, sender_factory=lambda: sender)

    assert await relay.relay_once() == 1
    assert sender.attempts == 1
    topic, key, value = sender.calls[0]
    assert topic == LEDGER_POSTED_TOPIC
    assert key == aggregate_id.encode("utf-8")
    body = json.loads(value)
    assert body["event_id"] == row_id
    assert body["event_type"] == "LedgerPosted"
    assert body["producer"] == "ledger"

    row = await _get_row(factory, row_id)
    assert row.published_at is not None
    assert row.dead_lettered_at is None
    assert row.publish_attempts == 0
    assert row.last_error is None
    assert row.next_attempt_at is None

    assert await relay.relay_once() == 0
    assert sender.attempts == 1
    assert REGISTRY.get_sample_value("platform_outbox_backlog", {"service": "ledger"}) == 0


async def test_no_publica_filas_programadas_para_mas_adelante(env) -> None:
    factory, settings = env
    sender = FakeSender()
    later = utcnow() + timedelta(hours=1)
    await _insert_row(factory, next_attempt_at=later)
    relay = OutboxRelay(factory, settings, sender_factory=lambda: sender)

    assert await relay.relay_once() == 0
    assert sender.attempts == 0


async def test_fallo_registra_intento_backoff_y_luego_publica(env) -> None:
    factory, settings = env
    sender = FakeSender(failures=[RuntimeError("boom")])
    row_id = await _insert_row(factory)
    relay = OutboxRelay(factory, settings, sender_factory=lambda: sender)

    assert await relay.relay_once() == 0
    row = await _get_row(factory, row_id)
    assert row.publish_attempts == 1
    assert row.last_error == "boom"
    assert _aware(row.next_attempt_at) is not None and _aware(row.next_attempt_at) > utcnow()
    assert row.published_at is None
    assert REGISTRY.get_sample_value("platform_outbox_backlog", {"service": "ledger"}) == 1

    await _clear_next_attempt(factory, row_id)
    assert await relay.relay_once() == 1
    row = await _get_row(factory, row_id)
    assert row.published_at is not None
    assert row.publish_attempts == 1
    assert row.last_error is None


async def test_fallo_de_conexion_corta_el_resto_del_batch(env) -> None:
    factory, settings = env
    from aiokafka.errors import KafkaConnectionError

    sender = FakeSender(failures=[KafkaConnectionError("sin broker")])
    first = await _insert_row(factory, aggregate_type="LedgerTransaction")
    second = await _insert_row(factory, aggregate_type="LedgerTransaction")
    relay = OutboxRelay(factory, settings, sender_factory=lambda: sender)

    assert await relay.relay_once() == 0
    assert sender.attempts == 1
    assert sender.closed is True
    for row_id in (first, second):
        row = await _get_row(factory, row_id)
        assert row.publish_attempts == 1
        assert row.published_at is None
        assert row.next_attempt_at is not None


async def test_tras_max_intentos_el_evento_se_envia_a_la_dlq(env) -> None:
    factory, _settings = env
    settings = LedgerSettings(outbox_max_attempts=2)
    sender = FakeSender(failures=[RuntimeError("fallo 1"), RuntimeError("fallo 2")])
    row_id = await _insert_row(factory, event_type="LedgerPosted", aggregate_type="LedgerTransaction")
    relay = OutboxRelay(factory, settings, sender_factory=lambda: sender)

    await relay.relay_once()  # intento 1 → backoff
    row = await _get_row(factory, row_id)
    assert row.publish_attempts == 1
    assert row.next_attempt_at is not None

    await _clear_next_attempt(factory, row_id)
    await relay.relay_once()  # intento 2 (= max) → siguiente ciclo va a la DLQ
    row = await _get_row(factory, row_id)
    assert row.publish_attempts == 2
    assert row.next_attempt_at is None
    assert row.published_at is None

    await relay.relay_once()  # rama DLQ
    row = await _get_row(factory, row_id)
    assert row.dead_lettered_at is not None
    assert row.published_at is None
    assert row.publish_attempts == 2

    assert len(sender.calls) == 1
    topic, key, value = sender.calls[0]
    original = topic_for_event("ledger", "LedgerTransaction", "LedgerPosted")
    assert topic == dlq_topic(original)
    assert key == row.aggregate_id.encode("utf-8")
    body = json.loads(value)
    assert body["dlq_reason"] == "max_attempts_exceeded"
    assert body["original_topic"] == original
    assert body["attempts"] == 2
    assert body["last_error"] == "fallo 2"
    assert body["envelope"]["event_id"] == row_id

    assert await relay.relay_once() == 0


# --------------------------------------------------------------------- kafka sender


async def test_kafka_event_sender_arranca_perezoso_y_cierra_sin_fallar() -> None:
    producer = AsyncMock()
    with patch("ledger.outbox.AIOKafkaProducer", return_value=producer) as factory:
        sender = KafkaEventSender("broker:9092", request_timeout_ms=1234)
    factory.assert_called_once_with(bootstrap_servers="broker:9092", acks="all", request_timeout_ms=1234)

    await sender.send(topic="ledger.t", key=b"k", value=b"v")
    assert producer.start.await_count == 1
    await sender.send(topic="ledger.t", key=b"k", value=b"v2")
    assert producer.start.await_count == 1
    assert producer.send_and_wait.await_count == 2
    producer.send_and_wait.assert_awaited_with("ledger.t", key=b"k", value=b"v2")

    producer.stop.side_effect = RuntimeError("ya detenido")
    await sender.close()  # suppress: no propaga
    producer.stop.assert_awaited_once()


# --------------------------------------------------------------------------- bucle


async def test_run_registra_el_fallo_del_ciclo_y_reintenta(env, monkeypatch) -> None:
    factory, settings = env
    relay = OutboxRelay(factory, settings, sender_factory=FakeSender)
    calls = 0

    async def boom() -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("ciclo roto")

    monkeypatch.setattr(relay, "relay_once", boom)
    await relay.start()
    await asyncio.sleep(0.2)
    relay._stopped.set()
    await asyncio.wait_for(relay._task, timeout=2)
    await relay.stop()
    assert calls >= 2


async def test_stop_sin_inicio_es_inofensivo(env) -> None:
    factory, settings = env
    relay = OutboxRelay(factory, settings, sender_factory=FakeSender)
    await relay.stop()
    assert relay._task is None


# -------------------------------------------------------------------------- backoff


def test_backoff_exponencial_acotado_con_jitter() -> None:
    assert compute_backoff_ms(1, base_ms=100, jitter=0) == 100
    assert compute_backoff_ms(2, base_ms=100, jitter=0) == 200
    assert compute_backoff_ms(3, base_ms=100, jitter=0) == 400
    assert compute_backoff_ms(30, base_ms=100, jitter=0) == 60_000

    rng = random.Random(0)
    for attempt in (1, 3, 5):
        value = compute_backoff_ms(attempt, base_ms=200, rng=rng)
        base = min(60_000, 200 * (2 ** (attempt - 1)))
        assert int(base * 0.75) <= value <= int(base * 1.25)
