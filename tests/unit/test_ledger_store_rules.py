"""Pruebas unitarias de reglas del `ledger.store` sin PostgreSQL.

Cubre `_assert_account_consistent` (coherencia cuenta/plan, L §7.1),
`_load_stored_posting` (idempotencia en curso, ADR-0010) y `_assert_reversal`
(estado de reversión, L §3) sobre SQLite. Documentado en ADR-0016.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from ledger.db import Base
from ledger.models import LedgerAccount, LedgerEntry, LedgerIdempotencyKey, LedgerTransaction
from ledger.postings import SYSTEM_OWNER_ID, EntryFact, plan_for_code
from ledger.store import _assert_account_consistent, _assert_reversal, _load_stored_posting
from platform_kernel.clock import utcnow
from platform_kernel.errors import AppError, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

CONTROL_ASSET = "1200.RECEIVABLE.PSP.USD"
CLIENT_LIABILITY = "2000.PAYABLE.CLIENT.USD.u1"
OWNER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


def _fact(code: str = CLIENT_LIABILITY, *, owner_id: uuid.UUID = OWNER_A) -> EntryFact:
    return EntryFact(
        position=1,
        account_code=code,
        direction="C",
        amount=Decimal("10.00"),
        currency="USD",
        owner_id=owner_id,
        owner_type="user",
    )


def _account(code: str, *, type_: str, owner_id: uuid.UUID, owner_type: str) -> LedgerAccount:
    return LedgerAccount(
        id=uuid.uuid4(),
        code=code,
        name=f"cuenta {code}",
        type=type_,
        currency="USD",
        owner_id=owner_id,
        owner_type=owner_type,
        is_control=False,
        created_at=utcnow(),
    )


# ----------------------------------------------------- consistencia cuenta vs plan


def test_cuenta_existente_con_tipo_distinto_al_plan_es_error() -> None:
    fact = _fact()
    plan = plan_for_code(CLIENT_LIABILITY)
    account = _account(CLIENT_LIABILITY, type_="asset", owner_id=OWNER_A, owner_type="user")
    with pytest.raises(ValidationError, match="existe con tipo"):
        _assert_account_consistent(account, fact, plan)


def test_cuenta_de_control_con_propietario_inesperado_es_error() -> None:
    fact = _fact(CONTROL_ASSET)
    plan = plan_for_code(CONTROL_ASSET)
    assert plan.is_control
    account = _account(CONTROL_ASSET, type_=plan.type, owner_id=OWNER_A, owner_type="user")
    with pytest.raises(ValidationError, match="propietario inesperado"):
        _assert_account_consistent(account, fact, plan)


def test_cuenta_de_control_con_owner_type_de_usuario_es_error() -> None:
    fact = _fact(CONTROL_ASSET)
    plan = plan_for_code(CONTROL_ASSET)
    account = _account(CONTROL_ASSET, type_=plan.type, owner_id=SYSTEM_OWNER_ID, owner_type="user")
    with pytest.raises(ValidationError, match="propietario inesperado"):
        _assert_account_consistent(account, fact, plan)


# --------------------------------------------------------------------- idempotencia


@pytest.fixture
async def env() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.execute(text("ATTACH DATABASE ':memory:' AS ledger"))
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[LedgerTransaction.__table__, LedgerEntry.__table__, LedgerIdempotencyKey.__table__],
            )
        )
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_load_sin_fila_es_idempotencia_en_curso(env) -> None:
    async with env() as session:
        with pytest.raises(AppError) as excinfo:
            await _load_stored_posting(session, idempotency_key="k1", request_hash="h1")
    assert excinfo.value.status_code == 409


async def test_load_sin_respuesta_es_idempotencia_en_curso(env) -> None:
    async with env() as session:
        session.add(
            LedgerIdempotencyKey(
                idempotency_key="k2",
                request_hash="h2",
                subject="u1",
                transaction_id=uuid.uuid4(),
                status_code=201,
                response=None,
                expires_at=utcnow() + timedelta(days=7),
            )
        )
        await session.commit()
        with pytest.raises(AppError) as excinfo:
            await _load_stored_posting(session, idempotency_key="k2", request_hash="h2")
    assert excinfo.value.status_code == 409


# ------------------------------------------------------------------------ reversiones


async def _seed_tx(session: AsyncSession) -> uuid.UUID:
    tx = LedgerTransaction(
        id=uuid.uuid4(),
        type="deposit",
        correlation_id=uuid.uuid4(),
        occurred_at=utcnow(),
        tx_metadata={},
    )
    session.add(tx)
    await session.flush()
    return tx.id


async def _seed_entry(session: AsyncSession, tx_id: uuid.UUID, position: int = 1) -> uuid.UUID:
    entry = LedgerEntry(
        id=uuid.uuid4(),
        transaction_id=tx_id,
        account_id=uuid.uuid4(),
        direction="C",
        amount=Decimal("10.00"),
        currency="USD",
        position=position,
    )
    session.add(entry)
    await session.flush()
    return entry.id


async def test_reversion_con_transaccion_inexistente_es_error(env) -> None:
    async with env() as session:
        with pytest.raises(ValidationError, match="no existe"):
            await _assert_reversal(session, uuid.uuid4(), [None])


async def test_reversion_con_entry_inexistente_es_error(env) -> None:
    async with env() as session:
        tx_id = await _seed_tx(session)
        await session.commit()
        with pytest.raises(ValidationError, match="no existe"):
            await _assert_reversal(session, tx_id, [uuid.uuid4()])


async def test_reversion_con_entry_de_otra_transaccion_es_error(env) -> None:
    async with env() as session:
        tx_id = await _seed_tx(session)
        otra_tx = await _seed_tx(session)
        entry_id = await _seed_entry(session, otra_tx)
        await session.commit()
        with pytest.raises(ValidationError, match="no pertenece"):
            await _assert_reversal(session, tx_id, [entry_id])


async def test_reversion_con_entries_validos_pasa_por_todos_los_asserts(env) -> None:
    async with env() as session:
        tx_id = await _seed_tx(session)
        primero = await _seed_entry(session, tx_id, 1)
        segundo = await _seed_entry(session, tx_id, 2)
        await session.commit()
        await _assert_reversal(session, tx_id, [None, primero, segundo])
