"""Pruebas de integración del pipeline outbox → Redpanda → Audit Service."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from audit.config import get_audit_settings
from audit.consumer import AuditEventConsumer
from audit.models import AuditRecord
from identity.config import IdentitySettings, get_identity_settings
from identity.db import get_session_factory
from identity.models import OutboxEvent
from identity.outbox import KafkaEventSender, OutboxRelay
from platform_kernel.clock import utcnow
from platform_kernel.events import EventEnvelope
from prometheus_client import REGISTRY
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration

BOOTSTRAP = os.environ.get("REDPANDA_BOOTSTRAP_SERVERS", "127.0.0.1:19092")
DEAD_BOOTSTRAP = "127.0.0.1:19093"  # sin listener: simula broker caído


@pytest.fixture
async def migrated(clean_dbs: None) -> None:
    """Recrea los schemas con las migraciones de identity y audit si faltaran."""
    from audit.migrate import run_migrations as run_audit_migrations
    from identity.migrate import run_migrations as run_identity_migrations

    await asyncio.to_thread(run_identity_migrations, get_identity_settings().database_url)
    await asyncio.to_thread(run_audit_migrations, get_audit_settings().audit_database_url)


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


async def _insert_row(
    factory: async_sessionmaker[AsyncSession],
    *,
    event_type: str,
    payload: dict[str, Any],
) -> tuple[str, str]:
    aggregate_id = str(uuid.uuid4())
    row = OutboxEvent(
        id=str(uuid.uuid4()),
        event_type=event_type,
        schema_version=1,
        aggregate_id=aggregate_id,
        aggregate_type="User",
        payload=payload,
        producer="identity",
        created_at=utcnow(),
    )
    async with factory() as session:
        session.add(row)
        await session.commit()
    return row.id, aggregate_id


async def _get_row(factory: async_sessionmaker[AsyncSession], row_id: str) -> OutboxEvent:
    async with factory() as session:
        return (await session.execute(select(OutboxEvent).where(OutboxEvent.id == row_id))).scalars().one()


async def _clear_next_attempt(factory: async_sessionmaker[AsyncSession], row_id: str) -> None:
    async with factory() as session:
        row = (await session.execute(select(OutboxEvent).where(OutboxEvent.id == row_id))).scalars().one()
        row.next_attempt_at = None
        await session.commit()


async def _consume_until(topic: str, event_id: str, *, timeout: float = 15.0) -> dict[str, Any]:
    """Lee `topic` desde el principio hasta encontrar el envelope del evento."""
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=BOOTSTRAP,
        group_id=f"probe-{uuid.uuid4().hex[:8]}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        request_timeout_ms=5000,
        client_id="outbox-pipeline-probe",
    )
    await consumer.start()
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise AssertionError(f"el evento {event_id} no llegó a {topic} en {timeout}s")
            try:
                message = await asyncio.wait_for(consumer.getone(), timeout=remaining)
            except TimeoutError:
                raise AssertionError(f"el evento {event_id} no llegó a {topic} en {timeout}s") from None
            try:
                body = json.loads(message.value)
            except Exception:
                continue
            if not isinstance(body, dict):
                continue
            nested = body.get("envelope")
            if body.get("event_id") == event_id or (isinstance(nested, dict) and nested.get("event_id") == event_id):
                return body
    finally:
        await consumer.stop()


async def _wait_audit_records(event_ids: set[str], *, timeout: float = 15.0) -> dict[str, AuditRecord]:
    from audit.db import get_session_factory as get_audit_factory

    factory = get_audit_factory()
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        async with factory() as session:
            rows = (
                (await session.execute(select(AuditRecord).where(AuditRecord.event_id.in_(event_ids)))).scalars().all()
            )
        if len(rows) == len(event_ids):
            return {row.event_id: row for row in rows}
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"audit no ingirió {event_ids - {r.event_id for r in rows}} en {timeout}s")
        await asyncio.sleep(0.25)


def _envelope(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        schema_version=1,
        aggregate_id=str(uuid.uuid4()),
        aggregate_type="User",
        timestamp=utcnow(),
        correlation_id=str(uuid.uuid4()),
        causation_id=str(uuid.uuid4()),
        producer="identity",
        payload=payload,
    )


# --------------------------------------------------------------- (a) relay → Redpanda


async def test_relay_publica_el_evento_en_redpanda(redpanda_available: None, migrated: None) -> None:
    factory = get_session_factory()
    row_id, aggregate_id = await _insert_row(factory, event_type="UserLoggedIn", payload={"ip_hash": "abc"})
    relay = OutboxRelay(factory, get_identity_settings())

    assert await relay.relay_once() >= 1

    body = await _consume_until("identity.user.logged_in", row_id)
    assert body["event_id"] == row_id
    assert body["event_type"] == "UserLoggedIn"
    assert body["aggregate_id"] == aggregate_id
    assert body["aggregate_type"] == "User"
    assert body["producer"] == "identity"
    assert body["schema_version"] == 1
    assert body["payload"] == {"ip_hash": "abc"}
    assert body["timestamp"]

    row = await _get_row(factory, row_id)
    assert row.published_at is not None
    assert row.dead_lettered_at is None
    assert row.publish_attempts == 0
    assert row.last_error is None

    published = REGISTRY.get_sample_value("platform_outbox_published_total", {"service": "identity"})
    assert published is not None and published >= 1


# -------------------------------------------- (b) max intentos → DLQ con broker caído


async def test_tras_max_intentos_el_evento_se_envia_a_la_dlq(redpanda_available: None, migrated: None) -> None:
    factory = get_session_factory()
    settings = IdentitySettings(outbox_max_attempts=2)
    row_id, aggregate_id = await _insert_row(factory, event_type="LoginFailed", payload={"reason": "bad_password"})
    broken = OutboxRelay(
        factory,
        settings,
        sender_factory=lambda: KafkaEventSender(DEAD_BOOTSTRAP, request_timeout_ms=300),
    )

    await broken.relay_once()  # fallo 1 → backoff
    row = await _get_row(factory, row_id)
    assert row.publish_attempts == 1
    assert row.published_at is None
    assert _aware(row.next_attempt_at) is not None

    await _clear_next_attempt(factory, row_id)
    await broken.relay_once()  # fallo 2 (= max) → el siguiente ciclo va a la DLQ
    row = await _get_row(factory, row_id)
    assert row.publish_attempts == 2
    assert row.next_attempt_at is None
    assert row.published_at is None

    healthy = OutboxRelay(factory, settings)  # broker real
    await healthy.relay_once()

    row = await _get_row(factory, row_id)
    assert row.dead_lettered_at is not None
    assert row.published_at is None
    assert row.publish_attempts == 2

    body = await _consume_until("dlq.identity.user.login_failed", row_id)
    assert body["dlq_reason"] == "max_attempts_exceeded"
    assert body["original_topic"] == "identity.user.login_failed"
    assert body["attempts"] == 2
    assert body["last_error"]
    envelope = body["envelope"]
    assert envelope["event_id"] == row_id
    assert envelope["event_type"] == "LoginFailed"
    assert envelope["aggregate_id"] == aggregate_id

    dead_lettered = REGISTRY.get_sample_value("platform_outbox_dead_lettered_total", {"service": "identity"})
    assert dead_lettered is not None and dead_lettered >= 1


# ------------------------------------------- (c) consumidor de audit: dedup y omisión


async def test_consumidor_de_audit_ingesta_dedup_y_mensajes_invalidos(redpanda_available: None, migrated: None) -> None:
    topic = "identity.user.registered"
    first = _envelope("UserRegistered", {"email_hash": "aaa"})
    second = _envelope("LoginFailed", {"reason": "bad_password"})

    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all", client_id="pipeline-producer")
    await producer.start()
    try:
        await producer.send_and_wait(topic, value=b"esto-no-es-un-json", key=b"invalido")
        await producer.send_and_wait(topic, value=first.model_dump_json().encode("utf-8"))
        await producer.send_and_wait(topic, value=first.model_dump_json().encode("utf-8"))  # duplicado
        await producer.send_and_wait(topic, value=second.model_dump_json().encode("utf-8"))
    finally:
        await producer.stop()

    from audit.db import get_session_factory as get_audit_factory

    consumer = AuditEventConsumer(get_audit_factory(), get_audit_settings())
    await consumer.start()
    try:
        records = await _wait_audit_records({first.event_id, second.event_id})
    finally:
        await consumer.stop()

    # el duplicado no genera segunda fila (dedup por event_id)
    async with get_audit_factory()() as session:
        duplicated = await session.scalar(
            select(func.count()).select_from(AuditRecord).where(AuditRecord.event_id == first.event_id)
        )
    assert duplicated == 1

    # el mensaje inválido se omite y no bloquea a los siguientes (commit tras omitir)
    login = records[second.event_id]
    assert login.severity == "WARNING"
    assert login.payload == {"reason": "bad_password"}
    assert login.correlation_id == second.correlation_id
    assert login.request_id == second.causation_id

    registered = records[first.event_id]
    assert registered.severity == "INFO"
    assert registered.aggregate_type == "User"
    assert registered.action == "UserRegistered"
    assert registered.recorded_at == first.timestamp
