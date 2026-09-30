"""routes - endpoints del Wallet Service (Q-api-map §2.5, BUILD-019/021/022).

Públicos con sesión de usuario: balances, movimientos, transferencias A→B y
tabla de conversiones. La validación de cuentas ocurre contra `accounts` y la
de saldo/escritura contra `ledger` (Q §3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from platform_kernel.auth import AuthContext, require_user
from platform_kernel.clock import utcnow
from platform_kernel.errors import AppError, ServiceUnavailableError
from platform_kernel.idempotency import idempotent_execute
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from wallet.config import WalletSettings, get_wallet_settings
from wallet.db import get_session
from wallet.schemas import (
    TYPE_VALIDATION,
    BalanceListOut,
    BalanceOut,
    ConversionRatesOut,
    HealthOut,
    MovementOut,
    MovementPageOut,
    PageInfo,
    ReadyOut,
    ReconciliationOut,
    TransferIn,
    TransferOut,
    WalletBalanceOut,
)
from wallet.service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    WalletService,
    canonical_amount,
    validate_range,
)

router = APIRouter()

SettingsDep = Annotated[WalletSettings, Depends(get_wallet_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _require_idempotency_key(idempotency_key: str | None) -> str:
    """Cabecera obligatoria con UUID (ADR-0010, Q-api-map §1.8)."""
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


def _balance_out(row: Any) -> BalanceOut:
    return BalanceOut(
        currency=row.currency,
        available=canonical_amount(row.available),
        reserved=canonical_amount(row.reserved),
        stale=row.stale,
        reconciled_at=row.reconciled_at,
    )


def _movement_out(row: Any) -> MovementOut:
    return MovementOut(
        movement_id=row.id,
        currency=row.currency,
        delta=canonical_amount(row.delta),
        direction=row.direction,
        tx_type=row.tx_type,
        ledger_transaction_id=row.ledger_transaction_id,
        occurred_at=row.occurred_at,
        created_at=row.created_at,
    )


@router.get("/healthz", response_model=HealthOut, tags=["system"])
async def healthz() -> HealthOut:
    return HealthOut(service="wallet", status="ok")


@router.get("/readyz", response_model=ReadyOut, tags=["system"])
async def readyz(session: SessionDep) -> ReadyOut:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise ServiceUnavailableError("base de datos no disponible") from exc
    return ReadyOut(status="ok")


@router.get(
    "/api/v1/wallet/balances",
    response_model=BalanceListOut,
    tags=["wallet"],
    summary="Balances por moneda del usuario autenticado",
)
async def list_balances(
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_user)],
) -> BalanceListOut:
    """Proyección local más `reconciliation` (BUILD-019): `stale=true` indica descuadre."""
    service = WalletService(session, settings)
    rows, as_of, stale, checked_at = await service.list_balances(uuid.UUID(auth.user_id))
    return BalanceListOut(
        data=[_balance_out(row) for row in rows],
        as_of=as_of,
        reconciliation=ReconciliationOut(stale=stale, checked_at=checked_at),
    )


@router.get(
    "/api/v1/wallet/balances/{currency}",
    response_model=WalletBalanceOut,
    tags=["wallet"],
    summary="Balance de una moneda",
)
async def get_balance(
    currency: str,
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_user)],
) -> WalletBalanceOut:
    service = WalletService(session, settings)
    row = await service.get_balance(uuid.UUID(auth.user_id), currency)
    out = _balance_out(row)
    return WalletBalanceOut(**out.model_dump(), as_of=utcnow())


@router.get(
    "/api/v1/wallet/transactions",
    response_model=MovementPageOut,
    tags=["wallet"],
    summary="Movimientos de saldo por rango (cursor, §2.5)",
)
async def list_transactions(
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_user)],
    from_: Annotated[datetime, Query(alias="from", description="Inicio del rango (obligatorio, ≤ 90 días)")],
    to: Annotated[datetime, Query(description="Fin del rango (obligatorio)")],
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> MovementPageOut:
    """Movimientos propios en `[from, to]` orden `(occurred_at, id)` desc (Q §2.5)."""
    start = from_ if from_.tzinfo is not None else from_.replace(tzinfo=UTC)
    end = to if to.tzinfo is not None else to.replace(tzinfo=UTC)
    validate_range(start, end)
    service = WalletService(session, settings)
    rows, has_more, next_cursor = await service.list_movements(
        user_id=uuid.UUID(auth.user_id),
        from_ts=start,
        to_ts=end,
        cursor=cursor,
        limit=limit,
    )
    return MovementPageOut(
        data=[_movement_out(row) for row in rows],
        page=PageInfo(next_cursor=next_cursor, prev_cursor=None, has_more=has_more, limit=limit),
    )


@router.post(
    "/api/v1/wallet/transfers",
    response_model=TransferOut,
    status_code=201,
    tags=["wallet"],
    summary="Transferencia A→B entre cuentas propias (§2.5)",
)
async def create_transfer(
    body: TransferIn,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    auth: Annotated[AuthContext, Depends(require_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TransferOut:
    """Ejecuta un posting `transfer` síncrono en ledger (única vía de escritura, §3).

    `Idempotency-Key` obligatorio (UUID): el replay devuelve la misma respuesta
    con `Idempotent-Replay: true` (ADR-0010/0011).
    """
    key = _require_idempotency_key(idempotency_key)
    service = WalletService(
        session,
        settings,
        ledger_client=getattr(request.app.state, "ledger_client", None),
        accounts_client=getattr(request.app.state, "accounts_client", None),
    )
    locks: list[Any] = request.app.state.transfer_locks
    lock = locks[uuid.UUID(auth.user_id).int % len(locks)]
    payload = body.model_dump(mode="json")

    async def run() -> tuple[int, dict[str, Any]]:
        data = await service.transfer(
            user_id=uuid.UUID(auth.user_id),
            body=body,
            idempotency_key=key,
            lock=lock,
        )
        return 201, data

    status_code, data, replayed = await idempotent_execute(
        store=request.app.state.idempotency,
        scope=f"wallet:transfer:{auth.user_id}",
        key=key,
        payload=payload,
        execute=run,
    )
    response.status_code = status_code
    response.headers["Idempotent-Replay"] = "true" if replayed else "false"
    return TransferOut.model_validate(data)


@router.get(
    "/api/v1/wallet/conversion-rates",
    response_model=ConversionRatesOut,
    tags=["wallet"],
    summary="Tabla de conversiones de divisas",
)
async def conversion_rates() -> ConversionRatesOut:
    """Tabla vacía en F2: el motor FX está como NO DETERMINADO en L §10 (sin tasas inventadas)."""
    return ConversionRatesOut(data=[], source="none", as_of=None)


__all__ = ["router"]
