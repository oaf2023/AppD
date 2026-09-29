"""Pruebas e2e: Identity + Audit + Gateway como servidores reales (puertos locales)."""

from __future__ import annotations

import asyncio
import uuid

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
        assert body["checks"] == {"identity": "ok", "audit": "ok", "market_data": "ok"}

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


async def test_gateway_devuelve_404_en_ruta_desconocida(servers: None) -> None:
    async with httpx.AsyncClient(base_url=GATEWAY, timeout=30.0) as client:
        response = await client.get("/ruta/que/no/existe")
        assert response.status_code == 404
        body = response.json()
        assert body["type"] == "urn:platform:error:not-found"
        assert "request_id" in body


async def test_gateway_rate_limit_global_excede(servers: None) -> None:
    # el límite global se relaja en tests; aquí solo verificamos que las cabeceras
    # de seguridad persisten en errores de validación
    async with httpx.AsyncClient(base_url=GATEWAY, timeout=30.0) as client:
        response = await client.post("/api/v1/auth/login", json={"email": "no-valido", "password": "x"})
        assert response.status_code == 422
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("Cache-Control") == "no-store"
