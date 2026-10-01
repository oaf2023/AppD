"""Pruebas unitarias de la purga de retención del ledger (SQLite en memoria).

El fichero no se llama `test_retention.py` para evitar la colisión de nombre de
módulo con `tests/integration/test_retention.py` (pytest importa los directorios
sin `__init__.py`), mismo criterio que `test_ledger_postings.py`.

Cubre las condiciones de retención de L §9 (claves vencidas en `expires_at` y
outbox finalizado 30 días tras publicar/DLQ), el borrado por tandas
(`retention_batch_size`), la métrica `platform_retention_purged_total` y el
ciclo `start`/`stop` de `RetentionSweep` (BUILD-025). Solo se crean las dos
tablas de retención: `ledger_accounts` no puede existir en SQLite porque su
`CHECK` usa la regex `~` de PostgreSQL. La red de seguridad append-only y la
reconstrucción de saldos se cubren en `tests/integration/test_retention.py`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from ledger.config import LedgerSettings
from ledger.models import LedgerIdempotencyKey, OutboxEvent
from ledger.retention import RetentionSweep, outbox_retention_cutoff
from platform_kernel.clock import utcnow
from prometheus_client import REGISTRY
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def _create_retention_tables(connection: Any) -> None:
    """Solo las tablas purgables (el resto del esquema exige PostgreSQL)."""
    LedgerIdempotencyKey.__table__.create(connection, checkfirst=True)
    OutboxEvent.__table__.create(connection, checkfirst=True)


@pytest.fixture
async def env() -> tuple[async_sessionmaker[AsyncSession], LedgerSettings]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.execute(text("ATTACH DATABASE ':memory:' AS ledger"))
        await conn.run_sync(_create_retention_tables)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    yield factory, LedgerSettings()
    await engine.dispose()


async def _seed_outbox(factory: async_sessionmaker[AsyncSession], *, created_at: Any = None, **fields: Any) -> str:
    row = OutboxEvent(
        id=str(uuid.uuid4()),
        event_type="LedgerPosted",
        schema_version=1,
        aggregate_id=str(uuid.uuid4()),
        aggregate_type="LedgerTransaction",
        payload={"source": "test"},
        producer="ledger",
        created_at=created_at or utcnow(),
        **fields,
    )
    async with factory() as session:
        session.add(row)
        await session.commit()
    return row.id


async def _seed_key(
    factory: async_sessionmaker[AsyncSession], key: str, *, expires_at: Any, transaction_id: uuid.UUID | None = None
) -> None:
    # SQLite no valida la FK a `ledger_transactions` (no existe en este fixture)
    async with factory() as session:
        session.add(
            LedgerIdempotencyKey(
                idempotency_key=key,
                request_hash="0" * 64,
                transaction_id=transaction_id or uuid.uuid4(),
                response={"source": "test"},
                expires_at=expires_at,
                created_at=utcnow(),
            )
        )
        await session.commit()


async def _count(factory: async_sessionmaker[AsyncSession], model: Any) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _ids(factory: async_sessionmaker[AsyncSession], model: Any) -> set[Any]:
    async with factory() as session:
        return set((await session.execute(select(model.id))).scalars())


# --------------------------------------------------------------------------- ajustes (L §9)


def test_ajustes_de_retencion_por_defecto() -> None:
    settings = LedgerSettings()
    assert settings.retention_sweep_enabled is True
    assert settings.retention_sweep_interval_seconds == 3600
    assert settings.retention_batch_size == 1000
    assert settings.outbox_retention_days == 30
    # el TTL de idempotencia sigue viviendo en la fila, no en un setting de purga
    assert settings.idempotency_ttl_seconds == 7 * 24 * 60 * 60

    with pytest.raises(ValidationError):
        LedgerSettings(retention_batch_size=0)
    with pytest.raises(ValidationError):
        LedgerSettings(retention_sweep_interval_seconds=0)
    with pytest.raises(ValidationError):
        LedgerSettings(outbox_retention_days=0)


# --------------------------------------------------------------------------- condiciones (L §9)


async def test_el_corte_del_outbox_es_de_30_dias_tras_publicar(env) -> None:  # type: ignore[no-untyped-def]
    factory, settings = env
    now = utcnow()
    cutoff = outbox_retention_cutoff(now, settings.outbox_retention_days)
    assert cutoff == now - timedelta(days=30)

    publicado_en_el_limite = await _seed_outbox(factory, published_at=cutoff - timedelta(seconds=1))
    publicado_dentro = await _seed_outbox(factory, published_at=cutoff + timedelta(seconds=1))

    counts = await RetentionSweep(factory, settings).sweep_once()

    assert counts == {"idempotency_keys": 0, "outbox_events": 1}
    # el corte es inclusivo (`<=`): desaparece el publicado un segundo antes, no el posterior
    restantes = await _ids(factory, OutboxEvent)
    assert publicado_en_el_limite not in restantes
    assert publicado_dentro in restantes


async def test_sweep_once_purga_solo_vencidas_y_por_lotes(env) -> None:  # type: ignore[no-untyped-def]
    factory, _settings = env
    settings = LedgerSettings(retention_batch_size=2)
    now = utcnow()
    vencidos = [await _seed_outbox(factory, published_at=now - timedelta(days=31)) for _ in range(5)]
    await _seed_outbox(factory, published_at=now - timedelta(days=10))
    await _seed_outbox(factory, dead_lettered_at=now - timedelta(days=31))
    await _seed_outbox(factory, created_at=now - timedelta(days=60))  # pendiente: backlog
    await _seed_key(factory, "vencida-1", expires_at=now - timedelta(days=1))
    await _seed_key(factory, "vencida-2", expires_at=now - timedelta(days=8))
    await _seed_key(factory, "vigente", expires_at=now + timedelta(days=6))

    antes = (
        REGISTRY.get_sample_value("platform_retention_purged_total", {"service": "ledger", "kind": "outbox_event"})
        or 0.0
    )
    counts = await RetentionSweep(factory, settings).sweep_once()

    # 6 outbox vencidos en tandas de 2 → el bucle de batch corre 3 veces
    assert counts == {"idempotency_keys": 2, "outbox_events": 6}
    assert await _count(factory, OutboxEvent) == 2
    assert await _count(factory, LedgerIdempotencyKey) == 1
    despues = REGISTRY.get_sample_value(
        "platform_retention_purged_total", {"service": "ledger", "kind": "outbox_event"}
    )
    assert despues is not None and despues - antes == 6
    claves = REGISTRY.get_sample_value(
        "platform_retention_purged_total", {"service": "ledger", "kind": "idempotency_key"}
    )
    assert claves is not None and claves >= 2
    # las filas vencidas concretas desaparecen y las conservadas siguen
    restantes = await _ids(factory, OutboxEvent)
    assert len(restantes) == 2 and not (restantes & set(vencidos))


# --------------------------------------------------------------------------- ciclo de vida


async def test_ciclo_de_vida_start_stop(env) -> None:  # type: ignore[no-untyped-def]
    factory, _settings = env
    await _seed_outbox(factory, published_at=utcnow() - timedelta(days=31))
    sweep = RetentionSweep(factory, LedgerSettings(retention_sweep_interval_seconds=3600))
    assert sweep._task is None

    await sweep.start()
    assert sweep._task is not None
    assert sweep._task.get_name() == "ledger-retention-sweep"
    assert not sweep._stopped.is_set()

    # la primera pasada es inmediata: espera a que la task purgue el backlog
    for _ in range(100):
        if await _count(factory, OutboxEvent) == 0:
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("la task de retención no ejecutó sweep_once")

    await sweep.stop()
    assert sweep._task is None
    assert sweep._stopped.is_set()


async def test_el_ciclo_sobrevive_a_un_fallo_de_sesion(env) -> None:  # type: ignore[no-untyped-def]
    factory, _settings = env

    class _FallaLaPrimeraVez:
        """session_factory doble: la primera invocación falla, la segunda abre sesión."""

        def __init__(self) -> None:
            self.calls = 0
            self.retry = asyncio.Event()
            self._factory = factory

        def __call__(self) -> Any:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("sin conexión a la base de datos")
            self.retry.set()
            return self._factory()

    roto = _FallaLaPrimeraVez()
    # intervalo corto: tras el fallo, `_run` espera `retention_sweep_interval_seconds`
    sweep = RetentionSweep(roto, LedgerSettings(retention_sweep_interval_seconds=1))

    await sweep.start()
    try:
        await asyncio.wait_for(roto.retry.wait(), timeout=5)
        assert roto.calls >= 2
        assert not sweep._task.done()  # el fallo no mató la task
    finally:
        await sweep.stop()


async def test_stop_sin_inicio_y_salida_natural_de_la_task(env) -> None:  # type: ignore[no-untyped-def]
    factory, _settings = env
    sweep = RetentionSweep(factory, LedgerSettings())

    # sin task iniciada: `stop()` recorre la rama falsa de `if self._task`
    await sweep.stop()
    assert sweep._task is None

    # bandera ya puesta: `_run()` no entra al bucle y sale de forma natural
    sweep._stopped.set()
    await sweep._run()
