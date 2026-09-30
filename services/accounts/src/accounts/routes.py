"""routes — endpoints del Accounts Service (Q-api-map §2.4 y §3).

Públicos: lista/detalle/creación/ajuste de cuentas propias con sesión de usuario.
Internos: validación de cuenta para otros servicios con JWT de servicio.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from platform_kernel.auth import AuthContext, require_service, require_user
from platform_kernel.errors import AppError
from platform_kernel.idempotency import idempotent_execute
from sqlalchemy.ext.asyncio import AsyncSession

from accounts.config import AccountsSettings, get_accounts_settings
from accounts.db import get_session
from accounts.pagination import decode_cursor
from accounts.schemas import (
    AccountCreateIn,
    AccountOut,
    AccountPageOut,
    AccountPatchIn,
    AccountStatus,
    HealthOut,
    ReadyOut,
    account_out,
)
from accounts.service import AccountsService

router = APIRouter()

SettingsDep = Annotated[AccountsSettings, Depends(get_accounts_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]

TYPE_VALIDATION = "urn:platform:error:validation"


def _require_idempotency_key(idempotency_key: str | None) -> str:
    """Valida la cabecera obligatoria `Idempotency-Key` (ADR-0010, Q-api-map §1.8)."""
    if not idempotency_key:
        raise AppError(
            400,
            TYPE_VALIDATION,
            "Validación fallida",
            "Cabecera Idempotency-Key obligatoria en este endpoint (Q-api-map §1.8)",
        )
    try:
        return str(uuid.UUID(idempotency_key.strip()))
    except ValueError as exc:
        raise AppError(
            400,
            TYPE_VALIDATION,
            "Validación fallida",
            "Cabecera Idempotency-Key debe ser un UUID (Q-api-map §1.8)",
        ) from exc


@router.get("/healthz", response_model=HealthOut, tags=["system"])
async def healthz() -> HealthOut:
    return HealthOut()


@router.get("/readyz", response_model=ReadyOut, tags=["system"])
async def readyz(session: SessionDep) -> ReadyOut:
    from sqlalchemy import text

    await session.execute(text("SELECT 1"))
    return ReadyOut()


@router.get(
    "/api/v1/accounts",
    response_model=AccountPageOut,
    tags=["accounts"],
    summary="Lista las cuentas de trading propias (cursor, §1.4)",
)
async def list_accounts(
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
    status: AccountStatus | None = None,
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$", max_length=3)] = None,
) -> AccountPageOut:
    service = AccountsService(session, settings)
    return await service.list_accounts(
        user_id=uuid.UUID(auth.user_id),
        limit=limit,
        cursor=decode_cursor(cursor) if cursor else None,
        status=status,
        currency=currency,
    )


@router.post(
    "/api/v1/accounts",
    response_model=AccountOut,
    status_code=201,
    tags=["accounts"],
    summary="Crea una cuenta (DEMO; LIVE requiere KYC + flag, BUILD-020)",
)
async def create_account(
    body: AccountCreateIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_user)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Obligatorio: UUIDv7 por operación lógica (Q-api-map §1.8).",
        ),
    ] = None,
) -> AccountOut:
    """Crea la cuenta y sus eventos `AccountCreated`/`DemoAccountCreated`.

    Requiere sesión de usuario y `Idempotency-Key` (ausente o no UUID → `400`).
    El replay devuelve la misma respuesta con `Idempotent-Replay: true`.
    Step-up MFA: mecanismo aún no disponible en Fase 1 (deuda documentada).
    """
    key = _require_idempotency_key(idempotency_key)
    service = AccountsService(session, settings)
    payload = body.model_dump(mode="json")
    user_id = uuid.UUID(auth.user_id)

    async def run() -> tuple[int, dict[str, Any]]:
        jurisdiction = await service.resolve_jurisdiction(user_id, client=request.app.state.identity_client)
        account = await service.create_account(
            user_id=user_id,
            mode=body.mode,
            currency=body.currency or settings.demo_currency,
            jurisdiction=jurisdiction,
            alias=body.alias,
        )
        return 201, account_out(account).model_dump(mode="json")

    status_code, data, replayed = await idempotent_execute(
        store=request.app.state.idempotency,
        scope=f"accounts:create:{auth.user_id}",
        key=key,
        payload=payload,
        execute=run,
    )
    response.status_code = status_code
    response.headers["Idempotent-Replay"] = "true" if replayed else "false"
    response.headers["Location"] = f"/api/v1/accounts/{data['account_id']}"
    return AccountOut.model_validate(data)


@router.get(
    "/api/v1/accounts/{account_id}",
    response_model=AccountOut,
    tags=["accounts"],
    summary="Detalle de una cuenta propia",
)
async def get_account(
    account_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_user)],
) -> AccountOut:
    """Recurso ajeno o inexistente → misma respuesta `404` (§1.7.3, BOLA)."""
    service = AccountsService(session, settings)
    account = await service.get_account(user_id=uuid.UUID(auth.user_id), account_id=account_id)
    return account_out(account)


@router.patch(
    "/api/v1/accounts/{account_id}",
    response_model=AccountOut,
    tags=["accounts"],
    summary="Ajustes permitidos de la cuenta (alias)",
)
async def patch_account(
    account_id: uuid.UUID,
    body: AccountPatchIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AccountOut:
    service = AccountsService(session, settings)
    payload = body.model_dump(mode="json")
    user_id = uuid.UUID(auth.user_id)

    async def run() -> tuple[int, dict[str, Any]]:
        account = await service.patch_account(user_id=user_id, account_id=account_id, body=body)
        return 200, account_out(account).model_dump(mode="json")

    if idempotency_key:
        _, data, replayed = await idempotent_execute(
            store=request.app.state.idempotency,
            scope=f"accounts:update:{auth.user_id}",
            key=idempotency_key,
            payload=payload,
            execute=run,
        )
        response.headers["Idempotent-Replay"] = "true" if replayed else "false"
    else:
        _, data = await run()
    return AccountOut.model_validate(data)


@router.get(
    "/internal/v1/accounts/{account_id}",
    response_model=AccountOut,
    tags=["internal"],
    summary="Validación de cuenta para otros servicios (Q-api-map §3)",
)
async def get_account_internal(
    account_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    service_name: Annotated[str, Depends(require_service)],
) -> AccountOut:
    service = AccountsService(session, settings)
    account = await service.get_account_internal(account_id)
    return account_out(account)


__all__ = ["router"]
