"""Pruebas de integración de la retención del ledger (BUILD-025, L §9, ADR-0011).

Cubre la purga por TTL de `ledger_idempotency_keys` (7 días codificados en
`expires_at`) y de `outbox_events` (30 días tras publicar/DLQ), la red de
seguridad append-only sobre los asientos y la verificación clave de BUILD-025:
tras archivar, la reconstrucción de saldos y las lecturas financieras son
idénticas. Requiere PostgreSQL (`platform_ledger`).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from helpers import lifespan_client
from ledger.config import get_ledger_settings
from ledger.consumer import client_account_code
from ledger.db import get_session_factory, reset_engine
from ledger.models import LedgerEntry, LedgerIdempotencyKey, LedgerTransaction, OutboxEvent
from ledger.retention import RetentionSweep
from ledger.store import compute_owner_balances, get_posting
from platform_kernel.clock import utcnow
from platform_kernel.ids import new_uuid7
from platform_kernel.security.tokens import new_access_token, new_service_token
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

URL = "/internal/v1/postings"
OCCURRED = "2026-09-29T12:00:00Z"
CONTROL_ASSET = "1200.RECEIVABLE.PSP.USD"

SERVICE_TOKEN = new_service_token(
    service_name="identity",
    secret=os.environ["SERVICE_TOKEN_SECRET"],
    issuer="platform-identity",
    audience="platform-internal",
)
HEADERS = {"Authorization": f"Bearer {SERVICE_TOKEN}"}


@pytest.fixture
async def ledger_client(clean_dbs: None):  # type: ignore[no-untyped-def]
    """App ledger con lifespan real; relay, consumidor y purga de fondo apagados.

    El relay necesita Redpanda y la purga de fondo no interesa aquí: cada test
    construye su `RetentionSweep` y llama a `sweep_once()` de forma explícita.
    Las variables se fijan SOLO durante este fixture para no afectar al resto
    de la suite (mismo criterio que `test_ledger.py`).
    """
    names = ("OUTBOX_RELAY_ENABLED", "EVENT_CONSUMER_ENABLED", "RETENTION_SWEEP_ENABLED")
    previous = {name: os.environ.get(name) for name in names}
    os.environ.update({name: "false" for name in names})
    get_ledger_settings.cache_clear()
    reset_engine()

    from ledger.main import create_app

    try:
        async with lifespan_client(create_app()) as client:
            yield client
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_ledger_settings.cache_clear()
        reset_engine()


@asynccontextmanager
async def _ledger_app(**overrides: str) -> AsyncIterator[Any]:
    """App ledger con variables de entorno puntuales; las restaura al salir."""
    from ledger.main import create_app

    previous = {name: os.environ.get(name) for name in overrides}
    os.environ.update(overrides)
    get_ledger_settings.cache_clear()
    reset_engine()
    try:
        app = create_app()
        async with app.router.lifespan_context(app):
            yield app
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_ledger_settings.cache_clear()
        reset_engine()


def _user_headers(owner: uuid.UUID) -> dict[str, str]:
    token = new_access_token(
        user_id=str(owner),
        session_id=str(uuid.uuid4()),
        roles=["user"],
        secret=os.environ["JWT_SECRET"],
        issuer="platform-identity",
        audience="platform-api",
        ttl_seconds=900,
    )
    return {"Authorization": f"Bearer {token}"}


def _range_days(days: int = 1) -> dict[str, str]:
    """Rango `[now-days, now+1d)` para cubrir `created_at = now()` de la BD."""
    now = datetime.now(UTC)
    return {
        "from": (now - timedelta(days=days)).isoformat(),
        "to": (now + timedelta(days=1)).isoformat(),
    }


def _deposit(owner: uuid.UUID, amount: str = "1000.00") -> dict[str, Any]:
    return {
        "type": "deposit",
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": OCCURRED,
        "metadata": {"source": "test-retention"},
        "entries": [
            {"account_code": CONTROL_ASSET, "direction": "D", "amount": amount, "currency": "USD"},
            {
                "account_code": client_account_code("USD", owner),
                "direction": "C",
                "amount": amount,
                "currency": "USD",
                "owner_id": str(owner),
            },
        ],
    }


async def _post(client: Any, body: dict[str, Any], key: str) -> Any:  # type: ignore[no-untyped-def]
    return await client.post(URL, json=body, headers={**HEADERS, "Idempotency-Key": key})


async def _seed_transaction() -> uuid.UUID:
    transaction = LedgerTransaction(
        id=new_uuid7(),
        type="deposit",
        correlation_id=uuid.uuid4(),
        occurred_at=utcnow(),
        created_at=utcnow(),
    )
    factory = get_session_factory()
    async with factory() as session:
        session.add(transaction)
        await session.commit()
    return transaction.id


async def _seed_idempotency_key(key: str, transaction_id: uuid.UUID, *, expires_at: datetime) -> None:
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            LedgerIdempotencyKey(
                idempotency_key=key,
                request_hash="0" * 64,
                transaction_id=transaction_id,
                response={"transaction_id": str(transaction_id)},
                expires_at=expires_at,
                created_at=utcnow(),
            )
        )
        await session.commit()


async def _seed_outbox(*, created_at: datetime | None = None, **fields: Any) -> str:
    row = OutboxEvent(
        id=str(uuid.uuid4()),
        event_type="LedgerPosted",
        schema_version=1,
        aggregate_id=str(uuid.uuid4()),
        aggregate_type="LedgerTransaction",
        payload={"source": "test-retention"},
        producer="ledger",
        created_at=created_at or utcnow(),
        **fields,
    )
    factory = get_session_factory()
    async with factory() as session:
        session.add(row)
        await session.commit()
    return row.id


async def _existing(pk: Any, values: list[Any]) -> set[Any]:  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    async with factory() as session:
        return set((await session.execute(select(pk).where(pk.in_(values)))).scalars())


# ------------------------------------------------- purga de idempotencia (L §9, ADR-0010)


async def test_purga_solo_las_claves_de_idempotencia_vencidas(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """TTL 7 días en `expires_at`: se purga solo lo vencido y la clave queda reutilizable."""
    transaction_id = await _seed_transaction()
    vencida, vigente = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_idempotency_key(vencida, transaction_id, expires_at=utcnow() - timedelta(days=1))
    await _seed_idempotency_key(vigente, transaction_id, expires_at=utcnow() + timedelta(days=6))

    counts = await RetentionSweep(get_session_factory(), get_ledger_settings()).sweep_once()

    assert counts == {"idempotency_keys": 1, "outbox_events": 0}
    assert await _existing(LedgerIdempotencyKey.idempotency_key, [vencida, vigente]) == {vigente}

    # comportamiento documentado: la clave vencida purgada ya admite un posting nuevo
    nuevo = await _post(ledger_client, _deposit(uuid.uuid4()), vencida)
    assert nuevo.status_code == 201
    assert nuevo.headers["Idempotent-Replay"] == "false"

    # la purga nunca toca el historial: la transacción de la clave sigue presente (ADR-0011)
    factory = get_session_factory()
    async with factory() as session:
        persiste = await session.scalar(
            select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.id == transaction_id)
        )
    assert persiste == 1


# ------------------------------------------------------- purga del outbox (L §9, ADR-0011 §5)


async def test_purga_solo_el_outbox_finalizado_vencido(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """30 días tras `published_at`/`dead_lettered_at`; el backlog pendiente no se toca."""
    now = utcnow()
    publicado_vencido = await _seed_outbox(published_at=now - timedelta(days=31))
    dlq_vencido = await _seed_outbox(dead_lettered_at=now - timedelta(days=31))
    publicado_reciente = await _seed_outbox(published_at=now - timedelta(days=10))
    pendiente_viejo = await _seed_outbox(created_at=now - timedelta(days=40))
    semillas = [publicado_vencido, dlq_vencido, publicado_reciente, pendiente_viejo]

    counts = await RetentionSweep(get_session_factory(), get_ledger_settings()).sweep_once()

    assert counts == {"idempotency_keys": 0, "outbox_events": 2}
    assert await _existing(OutboxEvent.id, semillas) == {publicado_reciente, pendiente_viejo}


# ------------------------------------- BUILD-025: archivado no rompe la reconstrucción


async def test_archivado_no_rompe_la_reconstruccion_de_saldos(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """BUILD-025: tras purgar, saldos y lecturas financieras son idénticos (ADR-0011 §3)."""
    owner = uuid.uuid4()
    response = await _post(ledger_client, _deposit(owner), str(uuid.uuid4()))
    assert response.status_code == 201
    transaction_id = uuid.UUID(response.json()["transaction_id"])

    antes = await _snapshot(ledger_client, owner, transaction_id)

    # filas de retención vencidas para que la purga tenga algo que archivar
    await _seed_idempotency_key(str(uuid.uuid4()), transaction_id, expires_at=utcnow() - timedelta(days=1))
    await _seed_outbox(published_at=utcnow() - timedelta(days=31))

    counts = await RetentionSweep(get_session_factory(), get_ledger_settings()).sweep_once()
    assert counts["idempotency_keys"] >= 1
    assert counts["outbox_events"] >= 1

    despues = await _snapshot(ledger_client, owner, transaction_id)
    assert despues == antes


async def _snapshot(client: Any, owner: uuid.UUID, transaction_id: uuid.UUID) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Lecturas reconstruibles: saldos, posting, asientos y extractos del owner."""
    factory = get_session_factory()
    async with factory() as session:
        # Decimal exacto (sin float): la comparación de la lista es valor a valor
        balances = await compute_owner_balances(session)
        posting = await get_posting(session, transaction_id)

    headers = _user_headers(owner)
    entries = await client.get("/api/v1/ledger/entries", params=_range_days(), headers=headers)
    statements = await client.get("/api/v1/ledger/statements", headers=headers)
    assert entries.status_code == 200
    assert statements.status_code == 200
    statement_id = statements.json()["data"][0]["statement_id"]
    detail = await client.get(f"/api/v1/ledger/statements/{statement_id}", headers=headers)
    assert detail.status_code == 200
    return {
        "balances": balances,
        "posting": posting.model_dump(mode="json"),
        "entries": entries.json(),
        "statements": statements.json(),
        # `as_of` es el timestamp de la consulta, no el dato reconstruido
        "statement_detail": {k: v for k, v in detail.json().items() if k != "as_of"},
    }


# ------------------------------------------------------------- red de seguridad ORM (ADR-0011 §2)


async def test_no_se_puede_borrar_un_asiento(ledger_client) -> None:  # type: ignore[no-untyped-def]
    """`models._forbid` convierte cualquier DELETE de asiento en `RuntimeError`."""
    owner = uuid.uuid4()
    response = await _post(ledger_client, _deposit(owner), str(uuid.uuid4()))
    assert response.status_code == 201
    transaction_id = uuid.UUID(response.json()["transaction_id"])

    factory = get_session_factory()
    async with factory() as session:
        entry = (
            (
                await session.execute(
                    select(LedgerEntry).where(
                        LedgerEntry.transaction_id == transaction_id,
                        LedgerEntry.position == 1,
                    )
                )
            )
            .scalars()
            .one()
        )
        entry_id = entry.id
        await session.delete(entry)
        with pytest.raises(RuntimeError, match="append-only"):
            await session.flush()
        await session.rollback()

    assert await _existing(LedgerEntry.id, [entry_id]) == {entry_id}


# ------------------------------------------------------------------- lifespan (patrón OutboxRelay)


async def test_lifespan_arranca_y_detiene_retention_sweep(clean_dbs: None) -> None:
    async with _ledger_app(
        OUTBOX_RELAY_ENABLED="false",
        EVENT_CONSUMER_ENABLED="false",
        RETENTION_SWEEP_ENABLED="true",
    ) as app:
        sweep = app.state.retention_sweep
        assert isinstance(sweep, RetentionSweep)
        assert sweep._task is not None
        assert sweep._task.get_name() == "ledger-retention-sweep"
        assert not sweep._stopped.is_set()

        counts = await sweep.sweep_once()
        assert set(counts) == {"idempotency_keys", "outbox_events"}

    assert sweep._task is None
    assert sweep._stopped.is_set()


async def test_lifespan_omite_retention_sweep_si_esta_desactivado(clean_dbs: None) -> None:
    async with _ledger_app(
        OUTBOX_RELAY_ENABLED="false",
        EVENT_CONSUMER_ENABLED="false",
        RETENTION_SWEEP_ENABLED="false",
    ) as app:
        assert app.state.retention_sweep is None
