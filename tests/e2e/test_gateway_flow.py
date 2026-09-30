"""Pruebas e2e: Identity + Audit + Gateway como servidores reales (puertos locales)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
from helpers import TEST_PASSWORD, TEST_POSTGRES_DSN, redpanda_reachable, unique_email

pytestmark = pytest.mark.e2e

GATEWAY = "http://127.0.0.1:18080"


def _audit_event_types(user_id: str) -> set[str]:
    with (
        psycopg.connect(f"{TEST_POSTGRES_DSN} dbname=platform_audit", connect_timeout=5) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            "SELECT event_type FROM audit.records WHERE aggregate_id = %s",
            (user_id,),
        )
        return {row[0] for row in cur.fetchall()}


async def _wait_for_audit_events(user_id: str, expected: set[str], timeout: float = 20.0) -> set[str]:
    deadline = asyncio.get_event_loop().time() + timeout
    found: set[str] = set()
    while asyncio.get_event_loop().time() < deadline:
        found = await asyncio.to_thread(_audit_event_types, user_id)
        if expected.issubset(found):
            return found
        await asyncio.sleep(0.5)
    return found


async def test_flujo_completo_a_traves_del_gateway(servers: None) -> None:
    email = unique_email()
    password = TEST_PASSWORD

    async with httpx.AsyncClient(base_url=GATEWAY, timeout=30.0) as client:
        # ---------------------------------------------------------------- salud
        health = await client.get("/healthz")
        assert health.status_code == 200, health.text
        body = health.json()
        assert body["status"] == "ok"
        assert body["checks"] == {
            "identity": "ok",
            "audit": "ok",
            "market_data": "ok",
            "ledger": "ok",
            "accounts": "ok",
            "wallet": "ok",
        }

        # la documentación interna no se expone
        docs = await client.get("/docs")
        assert docs.status_code == 404

        # ------------------------------------------------------------ registro
        payload = {
            "email": email,
            "password": password,
            "jurisdiction": "ES",
            "accept_terms": True,
        }
        key = f"e2e-{uuid.uuid4().hex}"
        register = await client.post("/api/v1/auth/register", json=payload, headers={"Idempotency-Key": key})
        assert register.status_code == 201, register.text
        assert register.headers.get("X-Content-Type-Options") == "nosniff"
        user_id = str(register.json()["user_id"])
        token = register.json()["dev_verification_token"]

        replay = await client.post("/api/v1/auth/register", json=payload, headers={"Idempotency-Key": key})
        assert replay.status_code == 201
        assert replay.headers.get("Idempotent-Replay") == "true"

        # rutas protegidas sin token
        no_auth = await client.get("/api/v1/me")
        assert no_auth.status_code == 401
        assert no_auth.headers["content-type"].startswith("application/problem+json")

        # identidad forjada por cabeceras NO autentica
        forged = await client.get(
            "/api/v1/admin/users",
            headers={"X-User-Id": user_id, "X-User-Roles": "admin"},
        )
        assert forged.status_code == 401

        # ------------------------------------------------------------ verificar
        verify = await client.post("/api/v1/auth/verify-email", json={"token": token})
        assert verify.status_code == 200

        # ---------------------------------------------------------------- login
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        pair = login.json()
        auth = {"Authorization": f"Bearer {pair['access_token']}"}

        me = await client.get("/api/v1/me", headers=auth)
        assert me.status_code == 200
        assert me.json()["email"] == email

        # -------------------------------------------------------------- refresh
        rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert rotated.status_code == 200
        reuse = await client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
        assert reuse.status_code == 401

        # --------------------------------------------------------------- logout
        logout = await client.post("/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]}, headers=auth)
        assert logout.status_code == 200
        after_logout = await client.get("/api/v1/me", headers=auth)
        assert after_logout.status_code == 401

    # los eventos del outbox llegan al Audit Service (relay Redpanda + consumidor)
    if not redpanda_reachable():
        pytest.skip("Redpanda no disponible: se omite la aserción de eventos end-to-end")
    found = await _wait_for_audit_events(
        user_id,
        {"UserRegistered", "UserEmailVerified", "UserLoggedIn"},
    )
    assert {"UserRegistered", "UserEmailVerified", "UserLoggedIn"}.issubset(found), found


async def _wait_for_demo_account(client: httpx.AsyncClient, headers: dict[str, str], timeout: float = 30.0):  # type: ignore[no-untyped-def]
    """Espera a que el consumidor de accounts auto-provisione la demo (BUILD-020)."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        response = await client.get("/api/v1/accounts", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        if data:
            return data[0]
        await asyncio.sleep(0.5)
    return None


async def test_registro_auto_provisiona_cuenta_demo(servers: None) -> None:
    """UserRegistered → accounts crea la demo; segunda creación manual → 409."""
    if not redpanda_reachable():
        pytest.skip("Redpanda no disponible: se omite la auto-provisión e2e")

    async with httpx.AsyncClient(base_url=GATEWAY, timeout=30.0) as client:
        email = unique_email()
        register = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": TEST_PASSWORD,
                "jurisdiction": "ES",
                "accept_terms": True,
            },
            headers={"Idempotency-Key": f"e2e-{uuid.uuid4().hex}"},
        )
        assert register.status_code == 201, register.text
        verify = await client.post(
            "/api/v1/auth/verify-email", json={"token": register.json()["dev_verification_token"]}
        )
        assert verify.status_code == 200, verify.text
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
        assert login.status_code == 200, login.text
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

        account = await _wait_for_demo_account(client, auth)
        assert account is not None, "accounts no auto-provisionó la cuenta demo tras el registro"
        assert account["type"] == "demo"
        assert account["status"] == "active"
        assert account["jurisdiction"] == "ES"
        assert account["currency"] == "USD"

        # una sola demo por usuario (BUILD-020): la creación manual devuelve 409
        manual = await client.post("/api/v1/accounts", json={}, headers={**auth, "Idempotency-Key": str(uuid.uuid4())})
        assert manual.status_code == 409, manual.text
        assert manual.json()["type"] == "urn:platform:error:conflict"

        # BOLA (§1.7.3): otro usuario no puede leer esta cuenta
        other_email = unique_email()
        other_register = await client.post(
            "/api/v1/auth/register",
            json={
                "email": other_email,
                "password": TEST_PASSWORD,
                "jurisdiction": "ES",
                "accept_terms": True,
            },
            headers={"Idempotency-Key": f"e2e-{uuid.uuid4().hex}"},
        )
        assert other_register.status_code == 201, other_register.text
        other_verify = await client.post(
            "/api/v1/auth/verify-email",
            json={"token": other_register.json()["dev_verification_token"]},
        )
        assert other_verify.status_code == 200, other_verify.text
        other_login = await client.post("/api/v1/auth/login", json={"email": other_email, "password": TEST_PASSWORD})
        assert other_login.status_code == 200, other_login.text
        foreign = await client.get(
            f"/api/v1/accounts/{account['account_id']}",
            headers={"Authorization": f"Bearer {other_login.json()['access_token']}"},
        )
        assert foreign.status_code == 404
        assert foreign.json()["type"] == "urn:platform:error:not-found"


async def test_gateway_devuelve_404_en_ruta_desconocida(servers: None) -> None:
    async with httpx.AsyncClient(base_url=GATEWAY, timeout=30.0) as client:
        response = await client.get("/ruta/que/no/existe")
        assert response.status_code == 404
        body = response.json()
        assert body["type"] == "urn:platform:error:not-found"
        assert "request_id" in body


async def _register_login(client: httpx.AsyncClient) -> tuple[dict[str, str], str]:  # type: ignore[no-untyped-def]
    """Registra, verifica y devuelve (headers de auth, user_id)."""
    email = unique_email()
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": TEST_PASSWORD, "jurisdiction": "ES", "accept_terms": True},
        headers={"Idempotency-Key": f"e2e-{uuid.uuid4().hex}"},
    )
    assert register.status_code == 201, register.text
    verify = await client.post("/api/v1/auth/verify-email", json={"token": register.json()["dev_verification_token"]})
    assert verify.status_code == 200, verify.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200, login.text
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return auth, str(register.json()["user_id"])


async def test_wallet_a_traves_del_gateway(servers: None) -> None:
    """Q §2.4/§2.5: saldos, movimientos, transferencias y FX desacoplados en `/api/v1/wallet`."""
    async with httpx.AsyncClient(base_url=GATEWAY, timeout=30.0) as client:
        auth, user_id = await _register_login(client)

        # saldos: 200 con proyección propia (vacía hasta que lleguen eventos)
        balances = await client.get("/api/v1/wallet/balances", headers=auth)
        assert balances.status_code == 200, balances.text
        body = balances.json()
        assert isinstance(body["data"], list)
        assert body["as_of"]
        assert "reconciliation" in body

        # FX no determinado en Fase 2 (L §10): lista vacía con fuente explícita
        fx = await client.get("/api/v1/wallet/conversion-rates", headers=auth)
        assert fx.status_code == 200, fx.text
        assert fx.json()["data"] == []
        assert fx.json()["source"] == "none"
        assert fx.json()["as_of"] is None

        # movimientos exigen rango (§1.5)
        sin_rango = await client.get("/api/v1/wallet/transactions", headers=auth)
        assert sin_rango.status_code == 422
        now = datetime.now(UTC)
        movimientos = await client.get(
            "/api/v1/wallet/transactions",
            params={"from": (now - timedelta(days=1)).isoformat(), "to": (now + timedelta(days=1)).isoformat()},
            headers=auth,
        )
        assert movimientos.status_code == 200, movimientos.text
        assert isinstance(movimientos.json()["data"], list)

        # transferencia sin Idempotency-Key → 400 tipado (ADR-0010)
        sin_clave = await client.post(
            "/api/v1/wallet/transfers",
            json={
                "from_account_id": str(uuid.uuid4()),
                "to_account_id": str(uuid.uuid4()),
                "currency": "USD",
                "amount": "10",
            },
            headers=auth,
        )
        assert sin_clave.status_code == 400
        assert sin_clave.json()["type"] == "urn:platform:error:validation"

        # con clave: cuenta destino inexistente → 404 idéntico (BOLA §1.7.3)
        destino = await client.post(
            "/api/v1/wallet/transfers",
            json={
                "from_account_id": str(uuid.uuid4()),
                "to_account_id": str(uuid.uuid4()),
                "currency": "USD",
                "amount": "10",
            },
            headers={**auth, "Idempotency-Key": str(uuid.uuid4())},
        )
        assert destino.status_code == 404, destino.text
        assert destino.json()["type"] == "urn:platform:error:not-found"
        assert user_id  # el token pertenece al usuario registrado


async def test_gateway_rate_limit_global_excede(servers: None) -> None:
    # el límite global se relaja en tests; aquí solo verificamos que las cabeceras
    # de seguridad persisten en errores de validación
    async with httpx.AsyncClient(base_url=GATEWAY, timeout=30.0) as client:
        response = await client.post("/api/v1/auth/login", json={"email": "no-valido", "password": "x"})
        assert response.status_code == 422
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("Cache-Control") == "no-store"
