"""Pruebas de integración del Accounts Service (ASGI + PostgreSQL real).

Cubre Q-api-map §2.4 (creación demo/live con gating), §1.8 (Idempotency-Key
obligatorio), §1.4 (paginación por cursor opaco), §1.7.3 (BOLA), §3 (endpoint
interno con JWT de servicio), BUILD-020 (una sola demo por usuario +
auto-provisión desde `UserRegistered`) y BUILD-023 (matriz de jurisdicciones).
Requiere PostgreSQL (`platform_accounts`).
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta
from typing import Any

import pytest
from accounts.config import get_accounts_settings
from accounts.consumer import provision_demo_from_event
from accounts.db import get_session_factory
from accounts.models import Jurisdiction, OutboxEvent, TradingAccount
from platform_contracts import events as ev
from platform_kernel.clock import utcnow
from platform_kernel.events import build_event
from platform_kernel.security.tokens import new_access_token, new_service_token
from sqlalchemy import select

pytestmark = pytest.mark.integration

SERVICE_HEADERS = {
    "Authorization": "Bearer "
    + new_service_token(
        service_name="accounts",
        secret=os.environ["SERVICE_TOKEN_SECRET"],
        issuer="platform-identity",
        audience="platform-internal",
    )
}


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


def _auth(user_id: str | None = None, *, idem: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_token(user_id)}"}
    if idem:
        headers["Idempotency-Key"] = str(uuid.uuid4())
    return headers


async def _outbox_rows(account_id: str) -> list[OutboxEvent]:
    factory = get_session_factory()
    async with factory() as session:
        rows = await session.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == account_id))
        return list(rows.scalars())


async def _insert_live_accounts(user_id: uuid.UUID, count: int) -> None:
    factory = get_session_factory()
    base = utcnow()
    async with factory() as session:
        for i in range(count):
            session.add(
                TradingAccount(
                    user_id=user_id,
                    type="live",
                    currency="USD",
                    jurisdiction="ES",
                    alias=f"c{i}",
                    created_at=base + timedelta(seconds=i),
                )
            )
        await session.commit()


# ---------------------------------------------------------------------- sistema


async def test_healthz_y_readyz(accounts_client) -> None:  # type: ignore[no-untyped-def]
    health = await accounts_client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"service": "accounts", "status": "ok"}
    ready = await accounts_client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


async def test_endpoints_requieren_sesion_de_usuario(accounts_client) -> None:  # type: ignore[no-untyped-def]
    assert (await accounts_client.get("/api/v1/accounts")).status_code == 401
    post = await accounts_client.post("/api/v1/accounts", json={})
    assert post.status_code == 401
    assert post.headers["content-type"].startswith("application/problem+json")


# ------------------------------------------------------------------ Idempotencia


async def test_create_requiere_idempotency_key_uuid(accounts_client) -> None:  # type: ignore[no-untyped-def]
    headers = _auth()
    missing = await accounts_client.post("/api/v1/accounts", json={}, headers=headers)
    assert missing.status_code == 400
    assert missing.json()["type"] == "urn:platform:error:validation"

    bad = await accounts_client.post("/api/v1/accounts", json={}, headers={**headers, "Idempotency-Key": "no-es-uuid"})
    assert bad.status_code == 400
    assert bad.json()["type"] == "urn:platform:error:validation"


async def test_crea_demo_emitidos_eventos_y_replay(accounts_client) -> None:  # type: ignore[no-untyped-def]
    auth = {"Authorization": f"Bearer {_token()}"}
    headers = {**auth, "Idempotency-Key": str(uuid.uuid4())}
    response = await accounts_client.post("/api/v1/accounts", json={}, headers=headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["type"] == "demo"
    assert body["currency"] == "USD"
    assert body["jurisdiction"] == "ES"
    assert body["status"] == "active"
    assert body["leverage"] is None
    assert response.headers["Idempotent-Replay"] == "false"
    assert response.headers["Location"] == f"/api/v1/accounts/{body['account_id']}"

    # outbox transaccional: AMBOS eventos en la misma transacción que la cuenta (ADR-0007)
    rows = await _outbox_rows(body["account_id"])
    assert {row.event_type for row in rows} == {ev.ACCOUNT_CREATED, ev.DEMO_ACCOUNT_CREATED}
    demo_row = next(row for row in rows if row.event_type == ev.DEMO_ACCOUNT_CREATED)
    assert demo_row.payload["initial_balance"] == "10000"  # S-mvp-scope: ej. USD 10.000
    assert demo_row.payload["currency"] == "USD"
    assert demo_row.payload["user_id"] == body["user_id"]
    created_row = next(row for row in rows if row.event_type == ev.ACCOUNT_CREATED)
    assert created_row.payload == {
        "account_id": body["account_id"],
        "user_id": body["user_id"],
        "type": "demo",
        "currency": "USD",
        "jurisdiction": "ES",
        "leverage": None,
    }

    # replay: misma clave y mismo cuerpo → misma respuesta sin efectos nuevos (§1.8)
    replay = await accounts_client.post("/api/v1/accounts", json={}, headers=headers)
    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["account_id"] == body["account_id"]
    assert len(await _outbox_rows(body["account_id"])) == 2

    # clave reutilizada con otro cuerpo → 409 (uso incorrecto de la clave)
    misuse = await accounts_client.post("/api/v1/accounts", json={"alias": "otra"}, headers=headers)
    assert misuse.status_code == 409
    assert misuse.json()["type"] == "urn:platform:error:conflict"

    # segunda clave con la misma petición → 409: una sola demo por usuario (BUILD-020)
    duplicate = await accounts_client.post(
        "/api/v1/accounts", json={}, headers={**auth, "Idempotency-Key": str(uuid.uuid4())}
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["type"] == "urn:platform:error:conflict"
    assert len(await _outbox_rows(body["account_id"])) == 2


async def test_create_rechaza_cuenta_live(accounts_client) -> None:  # type: ignore[no-untyped-def]
    response = await accounts_client.post("/api/v1/accounts", json={"mode": "live"}, headers=_auth(idem=True))
    assert response.status_code == 403
    assert response.json()["type"] == "urn:platform:error:live-not-enabled"
    assert response.json()["detail"].startswith("La creación de cuentas LIVE")


async def test_create_rechaza_jurisdiccion_bloqueada(accounts_client) -> None:  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    async with factory() as session:
        session.add(Jurisdiction(code="ES", status="blocked", policy_version=7))
        await session.commit()
    try:
        response = await accounts_client.post("/api/v1/accounts", json={}, headers=_auth(idem=True))
        assert response.status_code == 403
        body = response.json()
        assert body["type"] == "urn:platform:error:jurisdiction-blocked"
        assert "política v7" in body["detail"]
    finally:
        # se retira la fila para no afectar a otros tests (BD de sesión compartida)
        async with factory() as session:
            row = await session.get(Jurisdiction, "ES")
            if row is not None:
                await session.delete(row)
                await session.commit()


# -------------------------------------------------------------------- listado


async def test_listado_pagina_con_cursor_opaco(accounts_client) -> None:  # type: ignore[no-untyped-def]
    user_id = uuid.uuid4()
    await _insert_live_accounts(user_id, 3)
    headers = _auth(str(user_id))

    first = await accounts_client.get("/api/v1/accounts", params={"limit": 2}, headers=headers)
    assert first.status_code == 200
    page = first.json()
    assert [account["alias"] for account in page["data"]] == ["c2", "c1"]
    assert page["page"]["has_more"] is True
    assert page["page"]["prev_cursor"] is None
    assert page["page"]["limit"] == 2
    cursor = page["page"]["next_cursor"]
    assert cursor

    second = await accounts_client.get("/api/v1/accounts", params={"limit": 2, "cursor": cursor}, headers=headers)
    assert second.status_code == 200
    page2 = second.json()
    assert [account["alias"] for account in page2["data"]] == ["c0"]
    assert page2["page"]["has_more"] is False
    assert page2["page"]["next_cursor"] is None

    # cursor inválido → 422 tipado (§1.4)
    invalid = await accounts_client.get("/api/v1/accounts", params={"cursor": "!!cursor-invalido!!"}, headers=headers)
    assert invalid.status_code == 422
    assert invalid.json()["type"] == "urn:platform:error:validation"

    # filtros §1.4: status/currency
    closed = await accounts_client.get("/api/v1/accounts", params={"status": "closed"}, headers=headers)
    assert closed.status_code == 200
    assert closed.json()["data"] == []
    usd = await accounts_client.get("/api/v1/accounts", params={"currency": "USD"}, headers=headers)
    assert usd.status_code == 200
    assert len(usd.json()["data"]) == 3


# ---------------------------------------------------------- detalle y ajustes


async def test_detalle_propio_y_bola_404_idéntico(accounts_client) -> None:  # type: ignore[no-untyped-def]
    token = _token()
    own_headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}
    created = await accounts_client.post("/api/v1/accounts", json={}, headers=own_headers)
    assert created.status_code == 201, created.text
    account_id = created.json()["account_id"]

    own = await accounts_client.get(f"/api/v1/accounts/{account_id}", headers={"Authorization": f"Bearer {token}"})
    assert own.status_code == 200
    assert own.json()["account_id"] == account_id

    other = await accounts_client.get(f"/api/v1/accounts/{account_id}", headers=_auth())
    assert other.status_code == 404
    assert other.json()["type"] == "urn:platform:error:not-found"

    missing = await accounts_client.get(
        f"/api/v1/accounts/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )
    assert missing.status_code == 404
    # §1.7.3: recurso ajeno e inexistente son indistinguibles (anti-enumeración)
    assert missing.json()["detail"] == other.json()["detail"]


async def test_patch_actualiza_alias(accounts_client) -> None:  # type: ignore[no-untyped-def]
    token = _token()
    auth = {"Authorization": f"Bearer {token}"}
    created = await accounts_client.post(
        "/api/v1/accounts", json={}, headers={**auth, "Idempotency-Key": str(uuid.uuid4())}
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["account_id"]

    patched = await accounts_client.patch(
        f"/api/v1/accounts/{account_id}", json={"alias": "Mi cuenta demo"}, headers=auth
    )
    assert patched.status_code == 200
    assert patched.json()["alias"] == "Mi cuenta demo"

    # Idempotency-Key opcional en PATCH: replay devuelve la misma respuesta
    key_headers = {**auth, "Idempotency-Key": str(uuid.uuid4())}
    first = await accounts_client.patch(
        f"/api/v1/accounts/{account_id}", json={"alias": "Alias final"}, headers=key_headers
    )
    assert first.status_code == 200
    replay = await accounts_client.patch(
        f"/api/v1/accounts/{account_id}", json={"alias": "Alias final"}, headers=key_headers
    )
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["alias"] == "Alias final"


async def test_endpoint_interno_requiere_jwt_de_servicio(accounts_client) -> None:  # type: ignore[no-untyped-def]
    token = _token()
    created = await accounts_client.post(
        "/api/v1/accounts",
        json={},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["account_id"]

    internal = await accounts_client.get(f"/internal/v1/accounts/{account_id}", headers=SERVICE_HEADERS)
    assert internal.status_code == 200
    assert internal.json()["account_id"] == account_id

    as_user = await accounts_client.get(
        f"/internal/v1/accounts/{account_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert as_user.status_code == 401

    missing = await accounts_client.get(f"/internal/v1/accounts/{uuid.uuid4()}", headers=SERVICE_HEADERS)
    assert missing.status_code == 404
    assert missing.json()["type"] == "urn:platform:error:not-found"


# ---------------------------------------------------------------- consumidor


def _registered_event(user_id: uuid.UUID, jurisdiction: str = "PT", **payload: Any):
    body = {"user_id": str(user_id), "jurisdiction": jurisdiction, **payload}
    return build_event(
        event_type=ev.USER_REGISTERED,
        schema_version=ev.EVENT_TYPES[ev.USER_REGISTERED],
        aggregate_id=str(user_id),
        aggregate_type=ev.EVENT_AGGREGATE_TYPE[ev.USER_REGISTERED],
        producer="identity",
        payload=body,
    )


async def test_consumidor_auto_provisiona_demo_idempotente(accounts_client) -> None:  # type: ignore[no-untyped-def]
    settings = get_accounts_settings()
    user_id = uuid.uuid4()
    envelope = _registered_event(user_id)

    factory = get_session_factory()
    async with factory() as session:
        assert await provision_demo_from_event(session, settings, envelope) is True
    # reentrega at-least-once → el índice único parcial hace el handler idempotente
    async with factory() as session:
        assert await provision_demo_from_event(session, settings, envelope) is False

    listed = await accounts_client.get("/api/v1/accounts", headers=_auth(str(user_id)))
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert len(data) == 1
    assert data[0]["type"] == "demo"
    assert data[0]["jurisdiction"] == "PT"  # jurisdicción tomada del evento origen
    assert data[0]["status"] == "active"

    rows = await _outbox_rows(data[0]["account_id"])
    assert {row.event_type for row in rows} == {ev.ACCOUNT_CREATED, ev.DEMO_ACCOUNT_CREATED}
    assert all(row.causation_id == envelope.event_id for row in rows)
    assert all(row.correlation_id == envelope.correlation_id for row in rows)


async def test_consumidor_omite_payload_invalido(accounts_client) -> None:  # type: ignore[no-untyped-def]
    settings = get_accounts_settings()
    envelope = build_event(
        event_type=ev.USER_REGISTERED,
        schema_version=ev.EVENT_TYPES[ev.USER_REGISTERED],
        aggregate_id=str(uuid.uuid4()),
        aggregate_type=ev.EVENT_AGGREGATE_TYPE[ev.USER_REGISTERED],
        producer="identity",
        payload={"sin": "user_id"},  # payload inválido: se omite para no bloquear el topic
    )
    factory = get_session_factory()
    async with factory() as session:
        assert await provision_demo_from_event(session, settings, envelope) is False


# ---------------------------------------------------------------------- cierre (Q §2.4, F2.3)


async def _create_demo(accounts_client, user_id: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    response = await accounts_client.post("/api/v1/accounts", json={}, headers=_auth(user_id, idem=True))
    assert response.status_code == 201, response.text
    return response.json()


async def test_close_saldo_cero_cierra_y_emite_account_closed(accounts_app, accounts_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    account = await _create_demo(accounts_client, user_id)

    # sin sesión → 401
    anonima = await accounts_client.post(f"/api/v1/accounts/{account['account_id']}/close")
    assert anonima.status_code == 401

    # saldo real 0 en ledger (fuente de verdad, Q §3): el cierre procede
    closed = await accounts_client.post(
        f"/api/v1/accounts/{account['account_id']}/close",
        headers=_auth(user_id, idem=True),
    )
    assert closed.status_code == 200, closed.text
    body = closed.json()
    assert body["status"] == "closed"
    assert body["closed_at"] is not None

    rows = await _outbox_rows(account["account_id"])
    closed_events = [row for row in rows if row.event_type == ev.ACCOUNT_CLOSED]
    assert len(closed_events) == 1
    assert closed_events[0].payload["account_id"] == account["account_id"]
    assert closed_events[0].payload["user_id"] == user_id
    assert closed_events[0].payload["currency"] == "USD"

    # segunda vez → 409 (ya cerrada)
    again = await accounts_client.post(
        f"/api/v1/accounts/{account['account_id']}/close",
        headers=_auth(user_id, idem=True),
    )
    assert again.status_code == 409


async def test_close_bloqueado_por_saldo_no_cero(accounts_app, accounts_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    account = await _create_demo(accounts_client, user_id)
    accounts_app.state.ledger_balances[(user_id, "USD")] = "123.45"

    response = await accounts_client.post(
        f"/api/v1/accounts/{account['account_id']}/close",
        headers=_auth(user_id, idem=True),
    )
    assert response.status_code == 409
    assert response.json()["type"] == "urn:platform:error:conflict"
    assert "saldo cero" in response.json()["detail"]

    rows = await _outbox_rows(account["account_id"])
    assert not [row for row in rows if row.event_type == ev.ACCOUNT_CLOSED]

    # la cuenta sigue activa
    detail = await accounts_client.get(f"/api/v1/accounts/{account['account_id']}", headers=_auth(user_id))
    assert detail.json()["status"] == "active"


async def test_close_bola_y_live_no_habilitado(accounts_app, accounts_client) -> None:  # type: ignore[no-untyped-def]
    owner = str(uuid.uuid4())
    account = await _create_demo(accounts_client, owner)

    # recurso ajeno → 404 (mismo que inexistente, §1.7.3)
    foreign = await accounts_client.post(
        f"/api/v1/accounts/{account['account_id']}/close",
        headers=_auth(str(uuid.uuid4()), idem=True),
    )
    assert foreign.status_code == 404

    # cuenta LIVE → 403 tipado (cierre LIVE requiere KYC, F6)
    live_user = uuid.uuid4()
    await _insert_live_accounts(live_user, 1)
    live = await accounts_client.get("/api/v1/accounts", headers=_auth(str(live_user)))
    live_id = live.json()["data"][0]["account_id"]
    live_close = await accounts_client.post(
        f"/api/v1/accounts/{live_id}/close",
        headers=_auth(str(live_user), idem=True),
    )
    assert live_close.status_code == 403
    assert live_close.json()["type"] == "urn:platform:error:live-not-enabled"


# ---------------------------------------------------------------------- recarga (BUILD-020, F2.3)


async def test_reload_requiere_idempotency_key(accounts_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    account = await _create_demo(accounts_client, user_id)
    account_id = account["account_id"]

    auth = _auth(user_id)
    sin_clave = await accounts_client.post(f"/api/v1/accounts/{account_id}/reload-demo", headers=auth)
    assert sin_clave.status_code == 400
    assert sin_clave.json()["type"] == "urn:platform:error:validation"

    bad = await accounts_client.post(
        f"/api/v1/accounts/{account_id}/reload-demo",
        headers={**auth, "Idempotency-Key": "no-es-uuid"},
    )
    assert bad.status_code == 400


async def test_reload_emite_demo_balance_reset_y_replay(accounts_app, accounts_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    account = await _create_demo(accounts_client, user_id)
    account_id = account["account_id"]
    accounts_app.state.ledger_balances[(user_id, "USD")] = "123.45"  # saldo previo real

    key = str(uuid.uuid4())
    headers = {**_auth(user_id), "Idempotency-Key": key}
    response = await accounts_client.post(f"/api/v1/accounts/{account_id}/reload-demo", headers=headers)
    assert response.status_code == 202, response.text
    assert response.headers["Idempotent-Replay"] == "false"
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["currency"] == "USD"
    assert body["previous_balance"] == "123.45"  # canónico ADR-0006
    assert body["new_balance"] == "10000"  # demo_initial_balance
    assert body["event_id"]

    rows = await _outbox_rows(account_id)
    resets = [row for row in rows if row.event_type == ev.DEMO_BALANCE_RESET]
    assert len(resets) == 1
    payload = resets[0].payload
    assert payload["user_id"] == user_id
    assert payload["currency"] == "USD"
    assert payload["new_balance"] == "10000"
    assert payload["previous_balance"] == "123.45"
    assert payload["triggered_by"] == "user"

    # replay: misma respuesta, un solo evento (#17)
    replay = await accounts_client.post(f"/api/v1/accounts/{account_id}/reload-demo", headers=headers)
    assert replay.status_code == 202
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json() == body
    rows = await _outbox_rows(account_id)
    assert len([row for row in rows if row.event_type == ev.DEMO_BALANCE_RESET]) == 1


async def test_reload_rechaza_cuentas_no_demo_o_cerradas(accounts_app, accounts_client) -> None:  # type: ignore[no-untyped-def]
    user_id = str(uuid.uuid4())
    account = await _create_demo(accounts_client, user_id)
    account_id = account["account_id"]

    # cerrar con saldo cero y luego recargar → 409
    cerrada = await accounts_client.post(f"/api/v1/accounts/{account_id}/close", headers=_auth(user_id, idem=True))
    assert cerrada.status_code == 200
    reload_cerrada = await accounts_client.post(
        f"/api/v1/accounts/{account_id}/reload-demo",
        headers={**_auth(user_id), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert reload_cerrada.status_code == 409

    # cuenta LIVE → 409 (sólo demo recargable)
    live_user = uuid.uuid4()
    await _insert_live_accounts(live_user, 1)
    live_id = (await accounts_client.get("/api/v1/accounts", headers=_auth(str(live_user)))).json()["data"][0][
        "account_id"
    ]
    reload_live = await accounts_client.post(
        f"/api/v1/accounts/{live_id}/reload-demo",
        headers={**_auth(str(live_user)), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert reload_live.status_code == 409

    # BOLA: otro usuario no recarga esta cuenta
    ajena = await accounts_client.post(
        f"/api/v1/accounts/{account_id}/reload-demo",
        headers={**_auth(str(uuid.uuid4())), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert ajena.status_code == 404
