"""Pruebas unitarias del relay transactional outbox → Redpanda (SQLite en memoria)."""

from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from identity.config import IdentitySettings
from identity.db import Base
from identity.models import OutboxEvent
from identity.outbox import EventSender, OutboxRelay, compute_backoff_ms
from platform_kernel.clock import utcnow
from prometheus_client import REGISTRY
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


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
async def env() -> tuple[async_sessionmaker[AsyncSession], IdentitySettings]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.execute(text("ATTACH DATABASE ':memory:' AS identity"))
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    yield factory, IdentitySettings()
    await engine.dispose()


async def _insert_row(
    factory: async_sessionmaker[AsyncSession],
    *,
    event_type: str = "UserRegistered",
    aggregate_type: str = "User",
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
        producer="identity",
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
    row_id = await _insert_row(
        factory, event_type="UserLoggedIn", aggregate_id=aggregate_id, payload={"ip_hash": "abc"}
    )
    relay = OutboxRelay(factory, settings, sender_factory=lambda: sender)

    assert await relay.relay_once() == 1
    assert sender.attempts == 1
    topic, key, value = sender.calls[0]
    assert topic == "identity.user.logged_in"
    assert key == aggregate_id.encode("utf-8")
    body = json.loads(value)
    assert body["event_id"] == row_id
    assert body["event_type"] == "UserLoggedIn"
    assert body["aggregate_id"] == aggregate_id
    assert body["aggregate_type"] == "User"
    assert body["producer"] == "identity"
    assert body["schema_version"] == 1
    assert body["payload"] == {"ip_hash": "abc"}

    row = await _get_row(factory, row_id)
    assert row.published_at is not None
    assert row.dead_lettered_at is None
    assert row.publish_attempts == 0
    assert row.last_error is None
    assert row.next_attempt_at is None

    # la fila publicada no vuelve a salir
    assert await relay.relay_once() == 0
    assert sender.attempts == 1
    assert REGISTRY.get_sample_value("platform_outbox_backlog", {"service": "identity"}) == 0


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
    assert REGISTRY.get_sample_value("platform_outbox_backlog", {"service": "identity"}) == 1

    # vencido el backoff, el siguiente ciclo publica sin incrementar intentos
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
    first = await _insert_row(factory, event_type="UserRegistered")
    second = await _insert_row(factory, event_type="UserEmailVerified")
    relay = OutboxRelay(factory, settings, sender_factory=lambda: sender)

    assert await relay.relay_once() == 0
    # solo se intentó enviar la primera fila: no se reintenta contra el broker caído
    assert sender.attempts == 1
    assert sender.closed is True
    for row_id in (first, second):
        row = await _get_row(factory, row_id)
        assert row.publish_attempts == 1
        assert row.published_at is None
        assert row.next_attempt_at is not None


async def test_tras_max_intentos_el_evento_se_envia_a_la_dlq(env) -> None:
    factory, _settings = env
    settings = IdentitySettings(outbox_max_attempts=2)
    sender = FakeSender(failures=[RuntimeError("fallo 1"), RuntimeError("fallo 2")])
    row_id = await _insert_row(factory, event_type="LoginFailed", aggregate_type="User")
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
    assert topic == "dlq.identity.user.login_failed"
    assert key == row.aggregate_id.encode("utf-8")
    body = json.loads(value)
    assert body["dlq_reason"] == "max_attempts_exceeded"
    assert body["original_topic"] == "identity.user.login_failed"
    assert body["attempts"] == 2
    assert body["last_error"] == "fallo 2"
    assert body["envelope"]["event_id"] == row_id
    assert body["envelope"]["event_type"] == "LoginFailed"

    # ya no hay nada pendiente de publicar
    assert await relay.relay_once() == 0


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
