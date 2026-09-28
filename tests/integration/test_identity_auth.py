"""Pruebas de integración del Identity Service (ASGI + PostgreSQL real)."""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from helpers import TEST_PASSWORD, unique_email
from identity import totp as totp_mod
from identity.db import get_session_factory
from identity.models import EmailOutbox, OutboxEvent, UserRole
from platform_kernel.security.tokens import decode_jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

JWT_SECRET = os.environ["JWT_SECRET"]


def _claims(token: str) -> dict[str, Any]:
    return decode_jwt(
        token,
        secret=JWT_SECRET,
        issuer="platform-identity",
        audience="platform-api",
        expected_type="access",
    )


async def _register(client, email: str, *, accept_terms: bool = True) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": TEST_PASSWORD,
            "jurisdiction": "ES",
            "accept_terms": accept_terms,
        },
    )
    return response  # type: ignore[no-any-return]


async def _verified_login(client, email: str) -> dict[str, Any]:
    """Registra, verifica el email y devuelve el par de tokens."""
    response = await _register(client, email)
    assert response.status_code == 201, response.text
    verify = await client.post("/api/v1/auth/verify-email", json={"token": response.json()["dev_verification_token"]})
    assert verify.status_code == 200, verify.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200, login.text
    return login.json()


async def _outbox_contains(user_id: str, event_type: str) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        rows = await session.execute(
            select(OutboxEvent).where(
                OutboxEvent.event_type == event_type,
                OutboxEvent.aggregate_id == user_id,
            )
        )
        return rows.scalars().first() is not None


# --------------------------------------------------------------------- flujo


async def test_registro_verificacion_login_me(identity_client) -> None:
    email = unique_email()
    response = await _register(identity_client, email)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == email
    assert data["email_verification_required"] is True
    assert data["dev_verification_token"]
    user_id = str(data["user_id"])

    # login sin verificar → prohibido
    blocked = await identity_client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Email no verificado"

    # verificar
    verify = await identity_client.post("/api/v1/auth/verify-email", json={"token": data["dev_verification_token"]})
    assert verify.status_code == 200

    # token de verificación de un solo uso
    reuse = await identity_client.post("/api/v1/auth/verify-email", json={"token": data["dev_verification_token"]})
    assert reuse.status_code == 401

    login = await identity_client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login.status_code == 200
    pair = login.json()
    assert pair["token_type"] == "bearer"
    assert 0 < pair["expires_in"] <= 900

    claims = _claims(pair["access_token"])
    assert claims["sub"] == user_id
    assert claims["sid"] == str(pair["session_id"])
    assert claims["roles"] == ["user"]

    me = await identity_client.get("/api/v1/me", headers={"Authorization": f"Bearer {pair['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert me.json()["email_verified"] is True

    # eventos outbox del usuario concreto
    assert await _outbox_contains(user_id, "UserRegistered")
    assert await _outbox_contains(user_id, "UserEmailVerified")
    assert await _outbox_contains(user_id, "UserLoggedIn")


async def test_me_sin_token_es_401(identity_client) -> None:
    response = await identity_client.get("/api/v1/me")
    assert response.status_code == 401
    body = response.json()
    assert body["status"] == 401
    assert "request_id" in body and "correlation_id" in body


async def test_registro_aceptacion_terminos_obligatoria(identity_client) -> None:
    response = await _register(identity_client, unique_email(), accept_terms=False)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_registro_email_duplicado_conflicto(identity_client) -> None:
    email = unique_email()
    assert (await _register(identity_client, email)).status_code == 201
    duplicate = await _register(identity_client, email)
    assert duplicate.status_code == 409
    assert duplicate.json()["type"] == "urn:platform:error:conflict"


async def test_registro_idempotente(identity_client) -> None:
    email = unique_email()
    key = f"idem-{uuid.uuid4().hex}"
    headers = {"Idempotency-Key": key}
    payload = {
        "email": email,
        "password": TEST_PASSWORD,
        "jurisdiction": "ES",
        "accept_terms": True,
    }
    first = await identity_client.post("/api/v1/auth/register", json=payload, headers=headers)
    second = await identity_client.post("/api/v1/auth/register", json=payload, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.headers.get("Idempotent-Replay") == "false"
    assert second.headers.get("Idempotent-Replay") == "true"
    assert first.json()["user_id"] == second.json()["user_id"]

    # misma clave con cuerpo distinto → 409
    conflict = await identity_client.post(
        "/api/v1/auth/register", json={**payload, "email": unique_email()}, headers=headers
    )
    assert conflict.status_code == 409


async def test_login_password_incorrecta_401(identity_client) -> None:
    email = unique_email()
    assert (await _register(identity_client, email)).status_code == 201
    response = await identity_client.post(
        "/api/v1/auth/login", json={"email": email, "password": "Password-Que-No-Es-123"}
    )
    assert response.status_code == 401


async def test_refresh_rotacion_y_deteccion_de_reuso(identity_client) -> None:
    email = unique_email()
    pair = await _verified_login(identity_client, email)

    refresh1 = await identity_client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert refresh1.status_code == 200
    rotated = refresh1.json()

    # el refresh original ya no sirve (rotación) → reuso detectado
    reuse = await identity_client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert reuse.status_code == 401
    assert "reutilizado" in reuse.json()["detail"]

    # la familia queda revocada: el refresh rotado también deja de valer
    after = await identity_client.post("/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert after.status_code == 401

    # y la sesión del access original queda inválida
    me = await identity_client.get("/api/v1/me", headers={"Authorization": f"Bearer {pair['access_token']}"})
    assert me.status_code == 401


async def test_logout_revoca_sesion_al_instante(identity_client) -> None:
    email = unique_email()
    pair = await _verified_login(identity_client, email)
    headers = {"Authorization": f"Bearer {pair['access_token']}"}

    logout = await identity_client.post(
        "/api/v1/auth/logout", json={"refresh_token": pair["refresh_token"]}, headers=headers
    )
    assert logout.status_code == 200

    me = await identity_client.get("/api/v1/me", headers=headers)
    assert me.status_code == 401
    refresh = await identity_client.post("/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]})
    assert refresh.status_code == 401


async def test_sesiones_listado_y_revocacion(identity_client) -> None:
    email = unique_email()
    pair1 = await _verified_login(identity_client, email)
    login2 = await identity_client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert login2.status_code == 200
    pair2 = login2.json()

    headers = {"Authorization": f"Bearer {pair1['access_token']}"}
    sessions = await identity_client.get("/api/v1/auth/sessions", headers=headers)
    assert sessions.status_code == 200
    assert len(sessions.json()) >= 2

    target = str(pair2["session_id"])
    revoke = await identity_client.delete(f"/api/v1/auth/sessions/{target}", headers=headers)
    assert revoke.status_code == 200

    refresh = await identity_client.post("/api/v1/auth/refresh", json={"refresh_token": pair2["refresh_token"]})
    assert refresh.status_code == 401


async def test_password_forgot_y_reset(identity_client) -> None:
    email = unique_email()
    registered = await _register(identity_client, email)
    assert registered.status_code == 201
    verify = await identity_client.post(
        "/api/v1/auth/verify-email", json={"token": registered.json()["dev_verification_token"]}
    )
    assert verify.status_code == 200

    forgot = await identity_client.post("/api/v1/auth/password/forgot", json={"email": email})
    assert forgot.status_code == 202

    factory = get_session_factory()
    async with factory() as session:
        row = (
            (
                await session.execute(
                    select(EmailOutbox)
                    .where(EmailOutbox.to_email == email, EmailOutbox.template == "password_reset")
                    .order_by(EmailOutbox.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        token = row.body_text.split(": ", 1)[1].strip()

    new_password = "Otra!Passw0rd-2026"
    reset = await identity_client.post(
        "/api/v1/auth/password/reset", json={"token": token, "new_password": new_password}
    )
    assert reset.status_code == 200

    old = await identity_client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert old.status_code == 401
    fresh = await identity_client.post("/api/v1/auth/login", json={"email": email, "password": new_password})
    assert fresh.status_code == 200


async def test_mfa_ciclo_completo(identity_client) -> None:
    email = unique_email()
    pair = await _verified_login(identity_client, email)
    headers = {"Authorization": f"Bearer {pair['access_token']}"}

    setup = await identity_client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert "otpauth://totp/" in setup.json()["otpauth_url"]

    # código incorrecto no activa MFA
    bad = await identity_client.post("/api/v1/auth/mfa/verify", json={"code": "000000"}, headers=headers)
    assert bad.status_code == 401

    enable = await identity_client.post(
        "/api/v1/auth/mfa/verify", json={"code": totp_mod.totp(secret)}, headers=headers
    )
    assert enable.status_code == 200

    # el login normal ahora exige MFA
    mfa_login = await identity_client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert mfa_login.status_code == 200
    mfa_data = mfa_login.json()
    assert mfa_data["mfa_required"] is True
    assert "access_token" not in mfa_data

    final = await identity_client.post(
        "/api/v1/auth/mfa/login",
        json={"mfa_token": mfa_data["mfa_token"], "code": totp_mod.totp(secret)},
    )
    assert final.status_code == 200
    assert final.json()["access_token"]

    # desactivar vuelve al flujo normal
    disable = await identity_client.request(
        "DELETE", "/api/v1/auth/mfa", json={"code": totp_mod.totp(secret)}, headers=headers
    )
    assert disable.status_code == 200
    normal = await identity_client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert normal.status_code == 200
    assert "access_token" in normal.json()


async def test_admin_requiere_rol_backoffice(identity_client) -> None:
    email = unique_email()
    pair = await _verified_login(identity_client, email)
    headers = {"Authorization": f"Bearer {pair['access_token']}"}

    forbidden = await identity_client.get("/api/v1/admin/users", headers=headers)
    assert forbidden.status_code == 403

    # otorgar rol admin en BD y volver a entrar (los roles van en el JWT)
    async with get_session_factory()() as session:  # type: ignore[misc]
        await _grant_role(session, uuid.UUID(pair["user"]["id"]), "admin")
    relogin = await identity_client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    admin_headers = {"Authorization": f"Bearer {relogin.json()['access_token']}"}
    assert "admin" in _claims(relogin.json()["access_token"])["roles"]

    allowed = await identity_client.get("/api/v1/admin/users", headers=admin_headers)
    assert allowed.status_code == 200
    assert any(u["email"] == email for u in allowed.json())


async def _grant_role(session: AsyncSession, user_id: uuid.UUID, role: str) -> None:
    session.add(UserRole(user_id=user_id, role=role))
    await session.commit()
