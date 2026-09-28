"""Pruebas de integración del Audit Service (ingesta, RBAC, append-only)."""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
from audit.db import get_session_factory
from audit.models import AuditRecord
from platform_contracts.audit import AuditBatchIn, AuditRecordIn
from platform_kernel.clock import utcnow
from platform_kernel.security.tokens import new_access_token, new_service_token
from sqlalchemy import select

pytestmark = pytest.mark.integration

SERVICE_TOKEN = new_service_token(
    service_name="identity",
    secret=os.environ["SERVICE_TOKEN_SECRET"],
    issuer="platform-identity",
    audience="platform-internal",
)


def _access_token(roles: list[str]) -> str:
    return new_access_token(
        user_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        roles=roles,
        secret=os.environ["JWT_SECRET"],
        issuer="platform-identity",
        audience="platform-api",
        ttl_seconds=900,
    )


def _record(event_type: str = "UserRegistered", event_id: str | None = None) -> dict[str, Any]:
    return AuditRecordIn(
        event_id=event_id or str(uuid.uuid4()),
        event_type=event_type,
        aggregate_type="User",
        aggregate_id=str(uuid.uuid4()),
        action=event_type,
        actor_type="user",
        payload={"demo": True},
        recorded_at=utcnow(),
    ).model_dump(mode="json")


async def test_ingesta_requiere_token_de_servicio(audit_client) -> None:
    anonymous = await audit_client.post("/internal/v1/audit-events", json={"records": [_record()]})
    assert anonymous.status_code == 401

    user_token = _access_token(["user"])
    wrong = await audit_client.post(
        "/internal/v1/audit-events",
        json={"records": [_record()]},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert wrong.status_code == 401


async def test_ingesta_idempotente_por_event_id(audit_client) -> None:
    headers = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
    record = _record()

    first = await audit_client.post("/internal/v1/audit-events", json={"records": [record]}, headers=headers)
    assert first.status_code == 200
    assert first.json() == {"accepted": 1, "duplicates": 0}

    second = await audit_client.post("/internal/v1/audit-events", json={"records": [record]}, headers=headers)
    assert second.status_code == 200
    assert second.json() == {"accepted": 0, "duplicates": 1}


async def test_consulta_requiere_rol_backoffice(audit_client) -> None:
    no_auth = await audit_client.get("/api/v1/audit-events")
    assert no_auth.status_code == 401

    user_token = _access_token(["user"])
    forbidden = await audit_client.get("/api/v1/audit-events", headers={"Authorization": f"Bearer {user_token}"})
    assert forbidden.status_code == 403

    admin_token = _access_token(["admin"])
    allowed = await audit_client.get("/api/v1/audit-events", headers={"Authorization": f"Bearer {admin_token}"})
    assert allowed.status_code == 200
    assert "items" in allowed.json()


async def test_consulta_filtros_y_cursor(audit_client) -> None:
    headers = {
        "Authorization": f"Bearer {SERVICE_TOKEN}",
    }
    aggregate_id = str(uuid.uuid4())
    for event_type in ("UserRegistered", "UserLoggedIn", "SessionRevoked"):
        record = _record(event_type)
        record["aggregate_id"] = aggregate_id
        response = await audit_client.post("/internal/v1/audit-events", json={"records": [record]}, headers=headers)
        assert response.status_code == 200

    admin = {"Authorization": f"Bearer {_access_token(['admin'])}"}
    filtered = await audit_client.get("/api/v1/audit-events", params={"aggregate_id": aggregate_id}, headers=admin)
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 3

    page1 = await audit_client.get(
        "/api/v1/audit-events",
        params={"aggregate_id": aggregate_id, "limit": 2},
        headers=admin,
    )
    body1 = page1.json()
    assert len(body1["items"]) == 2
    assert body1["next_cursor"]

    page2 = await audit_client.get(
        "/api/v1/audit-events",
        params={"aggregate_id": aggregate_id, "limit": 2, "cursor": body1["next_cursor"]},
        headers=admin,
    )
    ids1 = {i["event_id"] for i in body1["items"]}
    ids2 = {i["event_id"] for i in page2.json()["items"]}
    assert ids1.isdisjoint(ids2)
    assert len(ids2) == 1


async def test_registros_son_append_only(audit_client) -> None:
    headers = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
    record = _record("SessionRevoked")
    response = await audit_client.post("/internal/v1/audit-events", json={"records": [record]}, headers=headers)
    assert response.status_code == 200

    factory = get_session_factory()
    async with factory() as session:
        row = (
            (await session.execute(select(AuditRecord).where(AuditRecord.event_id == record["event_id"])))
            .scalars()
            .one()
        )
        row.severity = "CRITICAL"
        with pytest.raises(RuntimeError, match="append-only"):
            await session.flush()
        await session.rollback()

    async with factory() as session:
        stale = (
            (await session.execute(select(AuditRecord).where(AuditRecord.event_id == record["event_id"])))
            .scalars()
            .one()
        )
        await session.delete(stale)
        with pytest.raises(RuntimeError, match="append-only"):
            await session.flush()


async def test_lote_validacion_minimo_un_registro(audit_client) -> None:
    headers = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
    empty = await audit_client.post("/internal/v1/audit-events", json={"records": []}, headers=headers)
    assert empty.status_code == 422


def test_contrato_lote_rechaza_vacio() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AuditBatchIn(records=[])
