"""Pruebas de integración del relay outbox de market-data → Redpanda (BUILD-029, K §4.2).

PostgreSQL real sobre `platform_market_data` (el JSONB del `OutboxRow` no
existe en SQLite): publicación con `FakeSender`, backoff y DLQ, el emparejamiento
transaccional `insert_suspension → outbox` (invariante K §4.2) y, con Redpanda
disponible, la entrega real en `market.symbols.changed` con el envelope P §1.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import psycopg
import pytest
from helpers import TEST_POSTGRES_DSN
from market_data.config import MarketDataSettings
from market_data.outbox import EventSender, OutboxRelay
from market_data.tables import OutboxRow
from platform_kernel.clock import utcnow
from prometheus_client import REGISTRY
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration

TOPIC = "market.symbols.changed"
BOOTSTRAP = os.environ.get("REDPANDA_BOOTSTRAP_SERVERS", "127.0.0.1:19092")
DEAD_BOOTSTRAP = "127.0.0.1:19093"  # sin listener: simula broker caído


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
async def env(clean_dbs: None) -> tuple[async_sessionmaker[AsyncSession], MarketDataSettings]:  # type: ignore[no-untyped-def]
    """Schema `market_data` migrado, outbox limpio y engine fresco por test."""
    from market_data.db import get_session_factory, reset_engine
    from market_data.migrate import run_migrations

    reset_engine()
    await asyncio.to_thread(run_migrations, os.environ["MARKET_DATA_DATABASE_URL"])
    with (
        psycopg.connect(f"{TEST_POSTGRES_DSN} dbname=platform_market_data", autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute("DELETE FROM market_data.outbox")
        cur.execute("DELETE FROM market_data.market_suspensions")
    yield get_session_factory(), MarketDataSettings(environment="test")
    reset_engine()


def _envelope(symbol: str = "EUR/USD") -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "SymbolUpdated",
        "schema_version": 1,
        "aggregate_id": symbol,
        "aggregate_type": "Symbol",
        "timestamp": utcnow().isoformat(),
        "correlation_id": str(uuid.uuid4()),
        "causation_id": None,
        "producer": "market-data",
        "payload": {"symbol": symbol, "event": "suspended", "code": "manual"},
    }


async def _insert_row(factory: async_sessionmaker[AsyncSession], *, payload: dict[str, Any]) -> str:
    row = OutboxRow(topic=TOPIC, event_type="SymbolUpdated", payload=payload, created_at=utcnow())
    async with factory() as session:
        session.add(row)
        await session.commit()
    return str(row.id)


async def _get_row(factory: async_sessionmaker[AsyncSession], row_id: str) -> OutboxRow:
    async with factory() as session:
        row = (await session.execute(select(OutboxRow).where(OutboxRow.id == uuid.UUID(row_id)))).scalars().one()
        return row


async def _clear_next_attempt(factory: async_sessionmaker[AsyncSession], row_id: str) -> None:
    async with factory() as session:
        row = (await session.execute(select(OutboxRow).where(OutboxRow.id == uuid.UUID(row_id)))).scalars().one()
        row.next_attempt_at = None
        await session.commit()


async def _consume_until(topic: str, event_id: str, *, timeout: float = 15.0) -> dict[str, Any]:
    """Lee `topic` desde el principio hasta encontrar el envelope del evento."""
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=BOOTSTRAP,
        group_id=f"probe-{uuid.uuid4().hex[:8]}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        request_timeout_ms=5000,
        client_id="market-data-outbox-probe",
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
            # el evento normal lleva event_id arriba; la DLQ lo anida en envelope
            found = body.get("event_id") or (body.get("envelope") or {}).get("event_id")
            if found == event_id:
                return body
    finally:
        await consumer.stop()


# ------------------------------------------------------------ flujo con doble


async def test_publica_el_envelope_y_marca_la_fila_como_publicada(env) -> None:  # type: ignore[no-untyped-def]
    factory, settings = env
    sender = FakeSender()
    envelope = _envelope()
    row_id = await _insert_row(factory, payload=envelope)
    relay = OutboxRelay(factory, settings, sender_factory=lambda: sender)

    assert await relay.relay_once() == 1
    assert sender.attempts == 1
    topic, key, value = sender.calls[0]
    assert topic == TOPIC
    assert key == b"EUR/USD"  # clave de partición = aggregate_id
    assert json.loads(value) == envelope  # el payload ya ES el envelope (P §1)

    row = await _get_row(factory, row_id)
    assert row.published_at is not None
    assert row.dead_lettered_at is None
    assert row.publish_attempts == 0
    assert row.last_error is None

    assert await relay.relay_once() == 0  # publicada: no vuelve a salir
    assert sender.attempts == 1
    assert REGISTRY.get_sample_value("platform_outbox_backlog", {"service": "market-data"}) == 0


async def test_fallo_registra_backoff_y_luego_publica(env) -> None:  # type: ignore[no-untyped-def]
    factory, settings = env
    sender = FakeSender(failures=[RuntimeError("boom")])
    row_id = await _insert_row(factory, payload=_envelope())
    relay = OutboxRelay(factory, settings, sender_factory=lambda: sender)

    assert await relay.relay_once() == 0
    row = await _get_row(factory, row_id)
    assert row.publish_attempts == 1
    assert row.last_error == "boom"
    assert row.next_attempt_at is not None and row.next_attempt_at > utcnow()
    assert row.published_at is None
    assert REGISTRY.get_sample_value("platform_outbox_backlog", {"service": "market-data"}) == 1

    await _clear_next_attempt(factory, row_id)
    assert await relay.relay_once() == 1
    row = await _get_row(factory, row_id)
    assert row.published_at is not None
    assert row.publish_attempts == 1
    assert row.last_error is None


async def test_tras_max_intentos_el_evento_se_envia_a_la_dlq(env) -> None:  # type: ignore[no-untyped-def]
    factory, _settings = env
    settings = MarketDataSettings(environment="test", outbox_max_attempts=2)
    sender = FakeSender(failures=[RuntimeError("fallo 1"), RuntimeError("fallo 2")])
    envelope = _envelope()
    row_id = await _insert_row(factory, payload=envelope)
    relay = OutboxRelay(factory, settings, sender_factory=lambda: sender)

    await relay.relay_once()  # intento 1 → backoff
    await _clear_next_attempt(factory, row_id)
    await relay.relay_once()  # intento 2 (= max) → siguiente ciclo va a la DLQ
    row = await _get_row(factory, row_id)
    assert row.publish_attempts == 2 and row.next_attempt_at is None and row.published_at is None

    assert await relay.relay_once() == 0  # rama DLQ: no cuenta como publicado
    row = await _get_row(factory, row_id)
    assert row.dead_lettered_at is not None
    assert row.published_at is None

    assert len(sender.calls) == 1
    topic, key, value = sender.calls[0]
    assert topic == "dlq.market.symbols.changed"
    assert key == b"EUR/USD"
    body = json.loads(value)
    assert body["dlq_reason"] == "max_attempts_exceeded"
    assert body["original_topic"] == TOPIC
    assert body["attempts"] == 2
    assert body["last_error"] == "fallo 2"
    assert body["envelope"] == envelope
    assert REGISTRY.get_sample_value("platform_outbox_dead_lettered_total", {"service": "market-data"}) >= 1


# ------------------------------------------- emparejamiento transaccional (K §4.2)


async def test_insert_suspension_escribe_un_outbox_pareado(env) -> None:  # type: ignore[no-untyped-def]
    from market_data.catalog import insert_suspension, outbox_rows

    factory, _settings = env
    async with factory() as session:
        await insert_suspension(session, symbol="EUR/USD", code="manual", reason="prueba")
        await session.commit()
        rows = await outbox_rows(session, event_type="SymbolUpdated")

    assert len(rows) == 1
    row = rows[0]
    assert row.topic == TOPIC
    assert row.published_at is None and row.dead_lettered_at is None
    assert row.payload["event_type"] == "SymbolUpdated"
    assert row.payload["aggregate_id"] == "EUR/USD"
    assert row.payload["producer"] == "market-data"
    assert row.payload["payload"] == {"symbol": "EUR/USD", "event": "suspended", "code": "manual"}


# ------------------------------------------------------- Redpanda real (CI/OMV)


async def test_relay_publica_el_evento_en_redpanda(env, redpanda_available: None) -> None:  # type: ignore[no-untyped-def]
    from market_data.catalog import insert_suspension, outbox_rows

    factory, settings = env
    async with factory() as session:
        await insert_suspension(session, symbol="EUR/USD", code="manual", reason="prueba redpanda")
        await session.commit()
        rows = await outbox_rows(session, event_type="SymbolUpdated")
    event_id = rows[0].payload["event_id"]

    relay = OutboxRelay(factory, settings)  # KafkaEventSender real
    assert await relay.relay_once() == 1

    body = await _consume_until(TOPIC, event_id)
    assert body["event_id"] == event_id
    assert body["event_type"] == "SymbolUpdated"
    assert body["aggregate_id"] == "EUR/USD"
    assert body["producer"] == "market-data"
    assert body["schema_version"] == 1
    assert body["payload"] == {"symbol": "EUR/USD", "event": "suspended", "code": "manual"}

    row = await _get_row(factory, str(rows[0].id))
    assert row.published_at is not None
    published = REGISTRY.get_sample_value("platform_outbox_published_total", {"service": "market-data"})
    assert published is not None and published >= 1
    await relay.stop()  # cierra el productor real


async def test_broker_caido_tras_max_intentos_va_a_la_dlq_en_redpanda(env, redpanda_available: None) -> None:  # type: ignore[no-untyped-def]
    from market_data.outbox import KafkaEventSender

    factory, _settings = env
    settings = MarketDataSettings(environment="test", outbox_max_attempts=2)
    envelope = _envelope()
    row_id = await _insert_row(factory, payload=envelope)
    broken = OutboxRelay(
        factory,
        settings,
        sender_factory=lambda: KafkaEventSender(DEAD_BOOTSTRAP, request_timeout_ms=300),
    )

    await broken.relay_once()  # fallo 1 → backoff
    await _clear_next_attempt(factory, row_id)
    await broken.relay_once()  # fallo 2 (= max) → el siguiente ciclo va a la DLQ
    row = await _get_row(factory, row_id)
    assert row.publish_attempts == 2 and row.next_attempt_at is None and row.published_at is None

    healthy = OutboxRelay(factory, settings)  # broker real
    assert await healthy.relay_once() == 0
    row = await _get_row(factory, row_id)
    assert row.dead_lettered_at is not None
    assert row.published_at is None

    body = await _consume_until("dlq.market.symbols.changed", envelope["event_id"])
    assert body["dlq_reason"] == "max_attempts_exceeded"
    assert body["original_topic"] == TOPIC
    assert body["attempts"] == 2
    assert body["envelope"] == envelope
    await healthy.stop()
    await broken.stop()
