"""routes — endpoints del Ledger Service.

Escritura: única vía de creación de asientos, interna e idempotente
(`Q-api-map.md` §3). Lectura: verificación de un posting por su identificador.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from platform_kernel.auth import require_service
from platform_kernel.errors import AppError
from sqlalchemy.ext.asyncio import AsyncSession

from ledger.db import get_session
from ledger.schemas import HealthOut, PostingOut, PostingsIn, ReadyOut
from ledger.store import get_posting, post_transaction

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]

TYPE_IDEMPOTENCY_KEY_MISSING = "urn:platform:error:validation"


def _require_idempotency_key(idempotency_key: str | None) -> str:
    """Valida la cabecera obligatoria `Idempotency-Key` (ADR-0010, Q-api-map §1.8)."""
    if not idempotency_key:
        raise AppError(
            400,
            TYPE_IDEMPOTENCY_KEY_MISSING,
            "Validación fallida",
            "Cabecera Idempotency-Key obligatoria en este endpoint (ADR-0010)",
        )
    try:
        return str(uuid.UUID(idempotency_key.strip()))
    except ValueError as exc:
        raise AppError(
            400,
            TYPE_IDEMPOTENCY_KEY_MISSING,
            "Validación fallida",
            "Cabecera Idempotency-Key debe ser un UUID (ADR-0010)",
        ) from exc


@router.get("/healthz", response_model=HealthOut, tags=["system"])
async def healthz() -> HealthOut:
    return HealthOut(service="ledger", status="ok")


@router.get("/readyz", response_model=ReadyOut, tags=["system"])
async def readyz(session: SessionDep) -> ReadyOut:
    from sqlalchemy import text

    await session.execute(text("SELECT 1"))
    return ReadyOut(status="ready")


@router.post(
    "/internal/v1/postings",
    response_model=PostingOut,
    status_code=201,
    tags=["internal"],
    summary="Registra un posting double-entry (única vía de escritura del ledger)",
)
async def create_posting(
    body: PostingsIn,
    session: SessionDep,
    response: Response,
    service: Annotated[str, Depends(require_service)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Obligatorio: UUID único por operación lógica (ADR-0010).",
        ),
    ] = None,
) -> PostingOut:
    """Crea una transacción ledger con sus asientos y su evento `LedgerPosted`.

    Requiere token de servicio y la cabecera `Idempotency-Key` (ausente o no
    UUID → `400` de validación, ADR-0010 §1). El replay devuelve la misma
    respuesta con `Idempotent-Replay: true`.
    """
    key = _require_idempotency_key(idempotency_key)
    posting, replayed = await post_transaction(
        session,
        body,
        idempotency_key=key,
        subject=service,
    )
    response.headers["Idempotent-Replay"] = "true" if replayed else "false"
    return posting


@router.get(
    "/internal/v1/postings/{posting_id}",
    response_model=PostingOut,
    tags=["internal"],
    summary="Recupera un posting por su identificador",
)
async def read_posting(
    posting_id: uuid.UUID,
    session: SessionDep,
    service: Annotated[str, Depends(require_service)],
) -> PostingOut:
    return await get_posting(session, posting_id)


__all__ = ["router"]
