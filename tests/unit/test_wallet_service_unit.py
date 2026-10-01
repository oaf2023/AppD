"""Pruebas unitarias de la lógica de `wallet.service` (sin servicios remotos).

Cubre `_key_occurred_at` (ADR-0010), `_check_pair` (BOLA/Q §2.5), `transfer`
con `lock=None` (serialización §2.5), `get_balance` (404) y las variantes de
payload de `apply_ledger_posted` (dedup + omisión, P-event-catalog §3.3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from platform_kernel.errors import ConflictError, NotFoundError
from platform_kernel.events import build_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from wallet.config import WalletSettings
from wallet.db import Base
from wallet.models import Balance, ProcessedEvent
from wallet.schemas import AccountRef, TransferIn
from wallet.service import WalletService, _key_occurred_at

USUARIO = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


@pytest.fixture
async def service() -> WalletService:
    from sqlalchemy import text

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.execute(text("ATTACH DATABASE ':memory:' AS wallet"))
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    svc = WalletService(factory(), WalletSettings())
    yield svc
    await svc.session.close()
    await engine.dispose()


def _cuenta(status: str, *, user_id: uuid.UUID = USUARIO) -> AccountRef:
    return AccountRef(
        account_id=uuid.uuid4(),
        user_id=user_id,
        type="spot",
        currency="USD",
        status=status,
    )


# ------------------------------------------------------------------ _key_occurred_at


def test_key_ocurred_at_deriva_el_timestamp_del_uuid7() -> None:
    value = _key_occurred_at(str(uuid.uuid7()))
    assert value.tzinfo is UTC
    assert abs((datetime.now(UTC) - value).total_seconds()) < 120


def test_key_ocurred_at_con_clave_no_uuid_usa_ahora() -> None:
    value = _key_occurred_at("no-es-uuid")
    assert abs((datetime.now(UTC) - value).total_seconds()) < 120


def test_key_ocurred_at_con_clave_fuera_de_rango_usa_ahora() -> None:
    value = _key_occurred_at(str(uuid.UUID(int=1)))
    assert abs((datetime.now(UTC) - value).total_seconds()) < 120


# ---------------------------------------------------------------------- _check_pair


def test_check_pair_rechaza_origen_inactivo() -> None:
    with pytest.raises(ConflictError, match="origen debe estar activa"):
        WalletService._check_pair(_cuenta("closed"), _cuenta("active"), "USD")


def test_check_pair_rechaza_destino_inactivo() -> None:
    with pytest.raises(ConflictError, match="destino debe estar activa"):
        WalletService._check_pair(_cuenta("active"), _cuenta("frozen"), "USD")


def test_check_pair_acepta_par_activo_homogeneo() -> None:
    WalletService._check_pair(_cuenta("active"), _cuenta("active"), "USD")


# ------------------------------------------------------------------------- transfer


async def test_transfer_sin_lock_espera_a_la_validacion_de_cuentas(service) -> None:
    origen = _cuenta("closed")

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=origen.model_dump(mode="json"))

    service._accounts_client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    body = TransferIn(
        from_account_id=origen.account_id,
        to_account_id=uuid.uuid4(),
        amount="10",
        currency="USD",
    )
    with pytest.raises(ConflictError, match="origen debe estar activa"):
        await service.transfer(user_id=USUARIO, body=body, idempotency_key=str(uuid.uuid7()), lock=None)


async def test_get_balance_sin_fila_es_not_found(service) -> None:
    with pytest.raises(NotFoundError, match="balance no encontrado"):
        await service.get_balance(uuid.uuid4(), "USD")


# ----------------------------------------------------------------- apply_ledger_posted


def _entry(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "owner_type": "user",
        "owner_id": str(USUARIO),
        "currency": "USD",
        "direction": "C",
        "amount": "10",
    }
    data.update(overrides)
    return data


def _envelope(payload: dict[str, object]):
    return build_event(
        event_type="ledger.posted.v1",
        schema_version=1,
        aggregate_id=str(uuid.uuid4()),
        aggregate_type="LedgerTransaction",
        producer="ledger",
        payload=payload,
    )


async def test_payload_con_occurred_at_sin_zona_horaria_se_asume_utc(service) -> None:
    envelope = _envelope(
        {
            "transaction_id": str(uuid.uuid4()),
            "occurred_at": "2026-09-30T12:00:00",
            "entries": [_entry()],
        }
    )
    assert await service.apply_ledger_posted(envelope) is True
    assert await service.session.get(ProcessedEvent, envelope.event_id) is not None


async def test_payload_con_entry_no_dict_se_omite(service) -> None:
    envelope = _envelope(
        {
            "transaction_id": str(uuid.uuid4()),
            "occurred_at": "2026-09-30T12:00:00+00:00",
            "entries": [42],
        }
    )
    assert await service.apply_ledger_posted(envelope) is False


async def test_payload_con_direccion_invalida_se_omite(service) -> None:
    envelope = _envelope(
        {
            "transaction_id": str(uuid.uuid4()),
            "occurred_at": "2026-09-30T12:00:00+00:00",
            "entries": [_entry(direction="X")],
        }
    )
    assert await service.apply_ledger_posted(envelope) is False


async def test_payload_con_delta_cero_no_genera_movimiento(service) -> None:
    envelope = _envelope(
        {
            "transaction_id": str(uuid.uuid4()),
            "occurred_at": "2026-09-30T12:00:00+00:00",
            "entries": [_entry(amount="0")],
        }
    )
    assert await service.apply_ledger_posted(envelope) is True
    balances = list((await service.session.execute(select(Balance))).scalars())
    assert balances == []
