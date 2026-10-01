"""Pruebas de integración del Wallet Service (ASGI + PostgreSQL real).

Cubre Q-api-map §2.5 (balances, movimientos, transferencias con Idempotency-Key
y conversiones), P-event-catalog §3.3 (deduplicación de `LedgerPosted`), BOLA
§1.7.3 y BUILD-019 (reconciliador con marca `stale`)/021/022. Requiere
PostgreSQL (`platform_wallet`); ledger y accounts se doblan con MockTransport
(estado en `app.state`, ver `integration/conftest.py`).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from platform_contracts import events as ev
from platform_kernel.clock import utcnow
from platform_kernel.events import EventEnvelope, build_event
from platform_kernel.security.tokens import new_access_token
from sqlalchemy import select
from wallet.config import get_wallet_settings
from wallet.consumer import WalletEventConsumer
from wallet.db import get_session_factory
from wallet.models import Balance, BalanceMovement, BalanceSnapshot, ProcessedEvent

pytestmark = pytest.mark.integration


def _token(user_id: str | None = None) -> str:
    return new_access_token(
        user_id=user_id or str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        roles=["user"],
        secret=os.environ["JWT_SECRET"],
        issuer="platform-identity",
        audience="platform-api",
        ttl_seconds=900,
    )


def _auth(user_id: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


def _entry(
    *,
    direction: str,
    amount: str,
    owner_id: str | None,
    owner_type: str | None = "user",
    currency: str = "USD",
) -> dict[str, Any]:
    return {
        "account_code": "2000.PAYABLE.CLIENT.USD.u_deadbeef",
        "direction": direction,
        "amount": amount,
        "currency": currency,
        "owner_id": owner_id,
        "owner_type": owner_type,
        "position": 1 if direction == "D" else 2,
    }


def _ledger_posted(
    entries: list[dict[str, Any]],
    *,
    tx_type: str = "deposit",
    transaction_id: str | None = None,
) -> EventEnvelope:
    return build_event(
        event_type=ev.LEDGER_POSTED,
        schema_version=1,
        aggregate_id=transaction_id or str(uuid.uuid4()),
        aggregate_type="LedgerTransaction",
        producer="ledger",
        payload={
            "transaction_id": transaction_id or str(uuid.uuid4()),
            "type": tx_type,
            "correlation_id": str(uuid.uuid4()),
            "causation_id": None,
            "occurred_at": utcnow().isoformat(),
            "reverses_tx_id": None,
            "metadata": {},
            "entries": entries,
        },
    )


async def _apply(envelope: EventEnvelope) -> bool:
    from wallet.service import WalletService

    factory = get_session_factory()
    async with factory() as session:
        return await WalletService(session, get_wallet_settings()).apply_ledger_posted(envelope)


async def _balances(user_id: str) -> list[Balance]:
    factory = get_session_factory()
    async with factory() as session:
        return list((await session.execute(select(Balance).where(Balance.user_id == uuid.UUID(user_id)))).scalars())


async def _fund(wallet_app, user_id: str, amount: str = "10000.00") -> None:
    """Simula la llegada de `LedgerPosted` con un depósito del usuario."""
    wallet_app.state.ledger_balances[(user_id, "USD")] = amount
    applied = await _apply(
        _ledger_posted(
            [
                _entry(direction="D", amount=amount, owner_id=None, owner_type="control"),
                _entry(direction="C", amount=amount, owner_id=user_id),
            ]
        )
    )
    assert applied is True


async def _register_account(wallet_app, account_id: str, user_id: str, *, type_: str = "demo") -> None:
    wallet_app.state.accounts_map[account_id] = {
        "account_id": account_id,
        "user_id": user_id,
        "type": type_,
        "currency": "USD",
        "status": "active",
    }


# --------------------------------------------------------------------------- sistema


async def test_healthz_y_readyz(wallet_client) -> None:  # type: ignore[no-untyped-def]
    health = await wallet_client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"service": "wallet", "status": "ok"}
    ready = await wallet_client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok"}


async def test_endpoints_requieren_sesion_de_usuario(wallet_client) -> None:  # type: ignore[no-untyped-def]
    from_ = (utcnow() - timedelta(days=1)).isoformat()
    to = utcnow().isoformat()
    assert (await wallet_client.get("/api/v1/wallet/balances")).status_code == 401
    assert (await wallet_client.get("/api/v1/wallet/transactions", params={"from": from_, "to": to})).status_code == 401
    post = await wallet_client.post("/api/v1/wallet/transfers", json={})
    assert post.status_code == 401
    assert post.headers["content-type"].startswith("application/problem+json")


# --------------------------------------------------------------------------- proyección (§3.3)


async def test_ledger_posted_proyecta_saldo_y_movimiento(wallet_app, wallet_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    await _fund(wallet_app, user_id, "10000.00")

    response = await wallet_client.get("/api/v1/wallet/balances", headers=_auth(user_id))
    assert response.status_code == 200
    data = response.json()
    assert data["data"] == [
        {
            "currency": "USD",
            "available": "10000",
            "reserved": "0",
            "stale": False,
            "reconciled_at": None,
        }
    ]
    assert data["reconciliation"] == {"stale": False, "checked_at": None}

    detail = await wallet_client.get("/api/v1/wallet/balances/USD", headers=_auth(user_id))
    assert detail.status_code == 200
    assert detail.json()["available"] == "10000"
    assert detail.json()["as_of"]

    factory = get_session_factory()
    async with factory() as session:
        movements = list(
            (
                await session.execute(select(BalanceMovement).where(BalanceMovement.user_id == uuid.UUID(user_id)))
            ).scalars()
        )
    assert len(movements) == 1
    assert movements[0].direction == "C"
    assert movements[0].delta == Decimal("10000.00")
    assert movements[0].tx_type == "deposit"


async def test_ledger_posted_es_deduplicado_por_event_id(wallet_app, wallet_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    envelope = _ledger_posted(
        [_entry(direction="C", amount="500", owner_id=user_id)],
    )
    assert await _apply(envelope) is True
    assert await _apply(envelope) is False  # reentrega at-least-once (§3.3)

    balances = await _balances(user_id)
    assert len(balances) == 1
    assert balances[0].available == Decimal("500")

    factory = get_session_factory()
    async with factory() as session:
        stored = await session.get(ProcessedEvent, envelope.event_id)
    assert stored is not None
    assert stored.event_type == ev.LEDGER_POSTED


async def test_solo_entries_de_usuario_se_proyectan(wallet_app, wallet_client) -> None:  # type: ignore[no-untyped-def]
    """Asientos de cuentas de control o system no tocan la proyección (L §4.1)."""
    control_owner = str(uuid.uuid4())
    envelope = _ledger_posted(
        [
            _entry(direction="D", amount="100", owner_id=None, owner_type="control"),
            _entry(direction="C", amount="100", owner_id=control_owner, owner_type="control"),
        ]
    )
    assert await _apply(envelope) is True
    assert await _balances(control_owner) == []


async def test_payload_invalido_se_omite_sin_tema_bloqueado() -> None:  # type: ignore[no-untyped-def]
    envelope = build_event(
        event_type=ev.LEDGER_POSTED,
        schema_version=1,
        aggregate_id=str(uuid.uuid4()),
        aggregate_type="LedgerTransaction",
        producer="ledger",
        payload={"entries": "no-es-lista"},
    )
    assert await _apply(envelope) is False


# --------------------------------------------------------------------------- movimientos (BUILD-022)


async def test_transacciones_exigen_rango_y_ventana_de_90_dias(wallet_client) -> None:  # type: ignore[no-untyped-def]
    auth = _auth()
    sin_rango = await wallet_client.get("/api/v1/wallet/transactions", headers=auth)
    assert sin_rango.status_code == 422
    assert sin_rango.json()["type"] == "urn:platform:error:validation"

    desde = utcnow() - timedelta(days=91)
    hasta = utcnow()
    rango_largo = await wallet_client.get(
        "/api/v1/wallet/transactions",
        params={"from": desde.isoformat(), "to": hasta.isoformat()},
        headers=auth,
    )
    assert rango_largo.status_code == 422
    assert rango_largo.json()["type"] == "urn:platform:error:validation"
    assert "90" in rango_largo.json()["detail"]  # la ventana, no un error de formato

    invertido = await wallet_client.get(
        "/api/v1/wallet/transactions",
        params={"from": hasta.isoformat(), "to": desde.isoformat()},
        headers=auth,
    )
    assert invertido.status_code == 422


async def test_transacciones_paginan_con_cursor_sin_duplicados(wallet_app, wallet_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    for amount in ("10", "20", "30"):
        await _apply(
            _ledger_posted(
                [_entry(direction="C", amount=amount, owner_id=user_id)],
                transaction_id=str(uuid.uuid4()),
            )
        )

    desde = (utcnow() - timedelta(days=1)).isoformat()
    hasta = (utcnow() + timedelta(days=1)).isoformat()
    params = {"from": desde, "to": hasta}

    first = await wallet_client.get(
        "/api/v1/wallet/transactions", params={**params, "limit": 2}, headers=_auth(user_id)
    )
    assert first.status_code == 200
    page = first.json()
    assert len(page["data"]) == 2
    assert page["page"]["has_more"] is True
    ids = [row["movement_id"] for row in page["data"]]

    second = await wallet_client.get(
        "/api/v1/wallet/transactions",
        params={**params, "limit": 2, "cursor": page["page"]["next_cursor"]},
        headers=_auth(user_id),
    )
    assert second.status_code == 200
    page2 = second.json()
    assert len(page2["data"]) == 1
    assert page2["page"]["has_more"] is False
    assert not set(ids) & {row["movement_id"] for row in page2["data"]}

    # cada movimiento sólo puede verse una vez en la ventana completa
    all_rows = page["data"] + page2["data"]
    assert len({row["movement_id"] for row in all_rows}) == 3
    assert all(row["delta"] in {"10", "20", "30"} for row in all_rows)


async def test_transacciones_ajenas_no_se_listan(wallet_app, wallet_client) -> None:  # type: ignore[no-untyped-def]
    owner = str(uuid.uuid4())
    stranger = str(uuid.uuid4())
    await _fund(wallet_app, owner, "777")
    desde = (utcnow() - timedelta(days=1)).isoformat()
    hasta = (utcnow() + timedelta(days=1)).isoformat()
    response = await wallet_client.get(
        "/api/v1/wallet/transactions",
        params={"from": desde, "to": hasta},
        headers=_auth(stranger),
    )
    assert response.status_code == 200
    assert response.json()["data"] == []


# --------------------------------------------------------------------------- transferencias (BUILD-021)


async def test_transf_requiere_idempotency_key_uuid(wallet_client) -> None:  # type: ignore[no-untyped-def]
    headers = _auth()
    body = {"from_account_id": str(uuid.uuid4()), "to_account_id": str(uuid.uuid4()), "amount": "10", "currency": "USD"}
    missing = await wallet_client.post("/api/v1/wallet/transfers", json=body, headers=headers)
    assert missing.status_code == 400
    assert missing.json()["type"] == "urn:platform:error:validation"

    bad = await wallet_client.post(
        "/api/v1/wallet/transfers", json=body, headers={**headers, "Idempotency-Key": "no-es-uuid"}
    )
    assert bad.status_code == 400


async def test_transf_exitosa_genera_posting_y_replay(wallet_app, wallet_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    from_id, to_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _register_account(wallet_app, from_id, user_id)
    await _register_account(wallet_app, to_id, other_id)
    wallet_app.state.ledger_balances[(user_id, "USD")] = "1000"

    key = str(uuid.uuid4())
    body = {"from_account_id": from_id, "to_account_id": to_id, "amount": "250.50", "currency": "USD"}
    headers = {**_auth(user_id), "Idempotency-Key": key}

    first = await wallet_client.post("/api/v1/wallet/transfers", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert first.headers["Idempotent-Replay"] == "false"
    data = first.json()
    assert data["status"] == "posted"
    assert data["amount"] == "250.5"  # canónico ADR-0006
    assert data["currency"] == "USD"

    assert len(wallet_app.state.ledger_postings) == 1
    posting = wallet_app.state.ledger_postings[0]
    assert posting["type"] == "transfer"
    assert posting["correlation_id"] == key  # clave UUID válida como correlación
    # occurred_at determinista de la clave: reintento idéntico no cambia el hash (ADR-0010)
    assert datetime.fromisoformat(posting["occurred_at"]) == datetime.fromisoformat(data["occurred_at"])
    assert [entry["direction"] for entry in posting["entries"]] == ["D", "C"]
    assert posting["entries"][0]["owner_id"] == user_id
    assert posting["entries"][1]["owner_id"] == other_id

    replay = await wallet_client.post("/api/v1/wallet/transfers", json=body, headers=headers)
    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json() == data
    assert len(wallet_app.state.ledger_postings) == 1  # un solo movimiento (BUILD-021)

    conflicto = await wallet_client.post("/api/v1/wallet/transfers", json={**body, "amount": "1"}, headers=headers)
    assert conflicto.status_code == 409


async def test_transf_bola_y_cuentas_invalidas(wallet_app, wallet_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    foreign_id = str(uuid.uuid4())
    own_id, foreign_account = str(uuid.uuid4()), str(uuid.uuid4())
    await _register_account(wallet_app, own_id, user_id)
    await _register_account(wallet_app, foreign_account, foreign_id)
    wallet_app.state.ledger_balances[(user_id, "USD")] = "100"

    base = {"amount": "10", "currency": "USD"}

    # origen ajeno → 404 (mismo que inexistente, §1.7.3)
    ajeno = await wallet_client.post(
        "/api/v1/wallet/transfers",
        json={**base, "from_account_id": foreign_account, "to_account_id": own_id},
        headers={**_auth(user_id), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert ajeno.status_code == 404

    # destino inexistente → 404
    inexistente = await wallet_client.post(
        "/api/v1/wallet/transfers",
        json={**base, "from_account_id": own_id, "to_account_id": str(uuid.uuid4())},
        headers={**_auth(user_id), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert inexistente.status_code == 404

    # misma cuenta → 422
    misma = await wallet_client.post(
        "/api/v1/wallet/transfers",
        json={**base, "from_account_id": own_id, "to_account_id": own_id},
        headers={**_auth(user_id), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert misma.status_code == 422

    # cruce demo/live rechazado (§2.5)
    await _register_account(wallet_app, foreign_account, user_id, type_="live")
    cruce = await wallet_client.post(
        "/api/v1/wallet/transfers",
        json={**base, "from_account_id": own_id, "to_account_id": foreign_account},
        headers={**_auth(user_id), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert cruce.status_code == 409

    # moneda distinta a la de las cuentas → 409
    await _register_account(wallet_app, foreign_account, foreign_id, type_="demo")
    moneda = await wallet_client.post(
        "/api/v1/wallet/transfers",
        json={**base, "currency": "EUR", "from_account_id": own_id, "to_account_id": foreign_account},
        headers={**_auth(user_id), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert moneda.status_code == 409


async def test_transf_sin_saldo_devuelve_409_tipado(wallet_app, wallet_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    from_id, to_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _register_account(wallet_app, from_id, user_id)
    await _register_account(wallet_app, to_id, str(uuid.uuid4()))
    wallet_app.state.ledger_balances[(user_id, "USD")] = "10"  # saldo real en ledger

    response = await wallet_client.post(
        "/api/v1/wallet/transfers",
        json={"from_account_id": from_id, "to_account_id": to_id, "amount": "999", "currency": "USD"},
        headers={**_auth(user_id), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 409
    assert response.json()["type"] == "urn:platform:error:insufficient-balance"
    assert wallet_app.state.ledger_postings == []  # nada se escribe sin saldo


async def test_transf_importe_invalido_devuelve_422(wallet_app, wallet_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    from_id, to_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _register_account(wallet_app, from_id, user_id)
    await _register_account(wallet_app, to_id, user_id)

    for amount in ("0", "-5", "no-numero"):
        response = await wallet_client.post(
            "/api/v1/wallet/transfers",
            json={"from_account_id": from_id, "to_account_id": to_id, "amount": amount, "currency": "USD"},
            headers={**_auth(user_id), "Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 422, amount


# --------------------------------------------------------------------------- conversiones (L §10)


async def test_conversion_rates_sin_motor_fx(wallet_client) -> None:  # type: ignore[no-untyped-def]
    response = await wallet_client.get("/api/v1/wallet/conversion-rates")
    assert response.status_code == 200
    body = response.json()
    assert body == {"data": [], "source": "none", "as_of": None}


# --------------------------------------------------------------------------- reconciliador (BUILD-019)


async def test_reconciliador_marca_stale_y_snapshot(wallet_app, wallet_client) -> None:  # type: ignore[no-untyped-def]
    from prometheus_client import REGISTRY
    from wallet.reconciler import Reconciler

    user_id = str(uuid.uuid4())
    await _fund(wallet_app, user_id, "100")  # proyección = 100
    # ledger aún sin ese saldo: hay descuadre real que detectar
    wallet_app.state.ledger_balances.pop((user_id, "USD"), None)

    factory = get_session_factory()
    reconciler = Reconciler(factory, get_wallet_settings(), client=wallet_app.state.ledger_client)

    before = REGISTRY.get_sample_value("platform_wallet_reconcile_mismatches_total") or 0.0
    stale = await reconciler.run_once()
    assert stale >= 1

    balances = await _balances(user_id)
    assert balances[0].stale is True
    assert balances[0].reconciled_at is not None
    after = REGISTRY.get_sample_value("platform_wallet_reconcile_mismatches_total")
    assert after is not None and after > before

    async with factory() as session:
        snapshots = list(
            (
                await session.execute(select(BalanceSnapshot).where(BalanceSnapshot.user_id == uuid.UUID(user_id)))
            ).scalars()
        )
    assert snapshots
    assert snapshots[-1].matched is False
    assert snapshots[-1].wallet_balance == Decimal("100")
    assert snapshots[-1].ledger_balance == Decimal(0)

    # al cuadrar ledger con la proyección, la marca desaparece
    wallet_app.state.ledger_balances[(user_id, "USD")] = "100"
    await reconciler.run_once()
    balances = await _balances(user_id)
    assert balances[0].stale is False

    # y el endpoint expone la última comparación
    response = await wallet_client.get("/api/v1/wallet/balances", headers=_auth(user_id))
    assert response.json()["reconciliation"]["stale"] is False
    assert response.json()["reconciliation"]["checked_at"] is not None


async def test_reconciliador_stop_cierra_el_cliente(wallet_app) -> None:  # type: ignore[no-untyped-def]
    import httpx
    from wallet.reconciler import Reconciler

    cliente = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [], "as_of": None}))
    )
    reconciler = Reconciler(get_session_factory(), get_wallet_settings(), client=cliente)
    # sin task iniciada: rama falsa de `if self._task`, pero cierra el cliente HTTP
    await reconciler.stop()
    assert reconciler._client is None


async def test_reconciliador_run_registra_fallo_y_sale_natural(wallet_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from wallet.reconciler import Reconciler

    settings = get_wallet_settings().model_copy(update={"reconcile_interval_seconds": 0})
    reconciler = Reconciler(get_session_factory(), settings)
    llamadas = 0

    async def _fallo() -> int:
        nonlocal llamadas
        llamadas += 1
        raise RuntimeError("ledger no responde")

    monkeypatch.setattr(reconciler, "run_once", _fallo)
    await reconciler.start()
    # intervalo efectivo 1 s: el primer `wait_for` expira (TimeoutError → continue)
    # y entra un segundo ciclo; después se marca la parada para la salida natural
    await asyncio.sleep(1.15)
    reconciler._stopped.set()
    assert await asyncio.wait_for(reconciler._task, timeout=5) is None
    assert llamadas >= 2
    await reconciler.stop()


async def test_reconciliador_detecta_saldo_sin_proyeccion(wallet_app) -> None:  # type: ignore[no-untyped-def]
    from wallet.reconciler import Reconciler

    user_id = str(uuid.uuid4())
    # ledger con saldo pero wallet sin fila de proyección → mismatch del segundo bucle
    wallet_app.state.ledger_balances[(user_id, "USD")] = "500"
    reconciler = Reconciler(get_session_factory(), get_wallet_settings(), client=wallet_app.state.ledger_client)

    stale = await reconciler.run_once()
    assert stale >= 1


# --------------------------------------------------------------------------- consumidor (Q §2.5)


class _ConsumidorFalso:
    """Doble de `AIOKafkaConsumer` que sólo registra los `commit`."""

    def __init__(self) -> None:
        self.commits: list[Any] = []

    async def commit(self, offsets: Any) -> None:
        self.commits.append(offsets)


def _mensaje(envelope: EventEnvelope, offset: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        topic="ledger.ledger_transaction.ledger_posted",
        partition=0,
        offset=offset,
        value=json.dumps(envelope.model_dump(mode="json")).encode(),
    )


async def test_consumidor_handle_descarta_mensaje_invalido(wallet_app) -> None:  # type: ignore[no-untyped-def]
    consumer = WalletEventConsumer(get_session_factory(), get_wallet_settings())
    fake = _ConsumidorFalso()
    await consumer._handle(fake, SimpleNamespace(topic="t", partition=0, offset=4, value=b"no es json"))
    assert len(fake.commits) == 1
    assert list(fake.commits[0].values()) == [5]


async def test_consumidor_handle_aplica_y_deduplica(wallet_app) -> None:  # type: ignore[no-untyped-def]
    consumer = WalletEventConsumer(get_session_factory(), get_wallet_settings())
    user_id = str(uuid.uuid4())
    envelope = _ledger_posted(
        [
            _entry(direction="D", amount="1000.00", owner_id=None, owner_type="control"),
            _entry(direction="C", amount="1000.00", owner_id=user_id),
        ]
    )
    fake = _ConsumidorFalso()
    await consumer._handle(fake, _mensaje(envelope, offset=0))
    await consumer._handle(fake, _mensaje(envelope, offset=1))
    assert len(fake.commits) == 2

    balances = await _balances(user_id)
    assert balances and balances[0].available == Decimal("1000")


async def test_consumidor_handle_omite_tipo_desconocido(wallet_app) -> None:  # type: ignore[no-untyped-def]
    consumer = WalletEventConsumer(get_session_factory(), get_wallet_settings())
    envelope = build_event(
        event_type=ev.DEMO_ACCOUNT_CREATED,
        schema_version=ev.EVENT_TYPES_PHASE2[ev.DEMO_ACCOUNT_CREATED],
        aggregate_id=str(uuid.uuid4()),
        aggregate_type=ev.EVENT_AGGREGATE_TYPE[ev.DEMO_ACCOUNT_CREATED],
        producer="accounts",
        payload={"user_id": str(uuid.uuid4()), "currency": "USD", "initial_balance": "100"},
    )
    fake = _ConsumidorFalso()
    await consumer._handle(fake, _mensaje(envelope, offset=0))
    assert len(fake.commits) == 1


async def test_consumidor_run_reintenta_tras_fallo(wallet_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    consumer = WalletEventConsumer(get_session_factory(), get_wallet_settings())
    calls = 0

    async def _fallo() -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            consumer._stopped.set()
        raise RuntimeError("redpanda no disponible")

    monkeypatch.setattr(consumer, "_consume", _fallo)
    monkeypatch.setattr("wallet.consumer.RETRY_DELAY_SECONDS", 0.05)
    await consumer.start()
    assert await asyncio.wait_for(consumer._task, timeout=5) is None
    assert calls >= 2
    await consumer.stop()


async def test_consumidor_stop_y_consume_con_doble_de_kafka(wallet_app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    consumer = WalletEventConsumer(get_session_factory(), get_wallet_settings())
    registros = [SimpleNamespace(topic="t", partition=0, offset=0, value=b"no es json")]
    commits: list[Any] = []

    class _FalsoKafka(_ConsumidorFalso):
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            super().__init__()
            self._peticiones = 0

        async def start(self) -> None:
            pass

        async def getone(self) -> Any:
            if self._peticiones < len(registros):
                registro = registros[self._peticiones]
                self._peticiones += 1
                return registro
            consumer._stopped.set()
            return registros[0]

        async def commit(self, offsets: Any) -> None:
            commits.append(offsets)
            await super().commit(offsets)

        async def stop(self) -> None:
            pass

    monkeypatch.setattr("wallet.consumer.AIOKafkaConsumer", _FalsoKafka)

    # stop() sin start(): rama falsa de `if self._task`
    await consumer.stop()
    assert consumer._task is None

    # con la bandera limpiada, `_consume` procesa un mensaje y sale al volver la bandera
    consumer._stopped.clear()
    await consumer._consume()
    assert len(commits) == 2
    assert consumer._consumer is None
