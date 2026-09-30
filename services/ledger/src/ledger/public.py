"""public — superficie pública de lectura del ledger (Q-api-map §2.6, BUILD-021/022).

Extractos por periodo, asientos propios y detalle de extracto con saldo inicial/final.
Solo lectura: los postings nunca se crean por API pública (§2.6); la escritura sigue
siendo `/internal/v1/postings`. Todo recurso se filtra por el `owner_id` del token
(BOLA §1.7.3) y los listados financieros exigen `from`/`to` con ventana ≤ 90 días (§1.5).

Convención de saldo: positivo = crédito del cliente (Σcréditos - Σdébitos, L §4.1),
el mismo criterio de `GET /internal/v1/balances` y de la proyección `wallet`.
"""

from __future__ import annotations

import base64
import binascii
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from platform_kernel.auth import AuthContext, require_user
from platform_kernel.clock import utcnow
from platform_kernel.errors import NotFoundError, ValidationError
from sqlalchemy import case, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ledger.db import get_session
from ledger.models import LedgerAccount, LedgerEntry, LedgerTransaction
from ledger.pagination import decode_cursor, encode_cursor
from ledger.postings import canonical_amount
from ledger.schemas import (
    EntryPageOut,
    PageInfo,
    PublicEntryOut,
    StatementOut,
    StatementPageOut,
    StatementPeriod,
    StatementSummaryOut,
)

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]

MAX_RANGE_DAYS = 90
STATEMENT_ID_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])-([A-Z]{3})$")

SIGN_EXPR = case((LedgerEntry.direction == "C", LedgerEntry.amount), else_=-LedgerEntry.amount)


def _amount(value: object) -> str:
    return canonical_amount(Decimal(value))  # type: ignore[arg-type]


def _amounts(opening: object, closing: object) -> tuple[str, str]:
    return _amount(opening), _amount(closing)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _validate_range(from_: datetime, to: datetime) -> tuple[datetime, datetime]:
    start, end = _as_utc(from_), _as_utc(to)
    if start >= end:
        raise ValidationError("`from` debe ser anterior a `to` (Q-api-map §1.5)")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise ValidationError(
            f"el rango `from`/`to` no puede superar los {MAX_RANGE_DAYS} días por consulta (Q-api-map §1.5)"
        )
    return start, end


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC) if month == 12 else datetime(year, month + 1, 1, tzinfo=UTC)
    return start, end


def encode_period_cursor(month: datetime, currency: str) -> str:
    raw = f"{month:%Y-%m}|{currency}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_period_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        period, _, currency = base64.urlsafe_b64decode(padded.encode()).decode().partition("|")
        year, month = period.split("-")
        return _month_bounds(int(year), int(month))[0], currency
    except (ValueError, binascii.Error) as exc:
        raise ValidationError("cursor inválido") from exc


def _entry_out(entry: LedgerEntry, account: LedgerAccount, transaction: LedgerTransaction) -> PublicEntryOut:
    return PublicEntryOut(
        entry_id=entry.id,
        transaction_id=entry.transaction_id,
        account_id=account.id,
        account_code=account.code,
        direction=entry.direction,  # type: ignore[arg-type]
        amount=canonical_amount(entry.amount),
        currency=entry.currency,
        tx_type=transaction.type,  # type: ignore[arg-type]
        occurred_at=transaction.occurred_at,
        created_at=entry.created_at,
    )


async def _owned_account(session: AsyncSession, user_id: uuid.UUID, account_id: uuid.UUID) -> LedgerAccount:
    account = await session.get(LedgerAccount, account_id)
    if account is None or account.owner_id != user_id or account.owner_type != "user":
        # §1.7.3 (BOLA): recurso ajeno o inexistente → misma respuesta 404
        raise NotFoundError("cuenta")
    return account


@router.get(
    "/api/v1/ledger/entries",
    response_model=EntryPageOut,
    tags=["ledger"],
    summary="Asientos propios por rango (cursor, §2.6)",
)
async def list_entries(
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_user)],
    from_: Annotated[datetime, Query(alias="from", description="Inicio del rango (obligatorio, ≤ 90 días)")],
    to: Annotated[datetime, Query(description="Fin del rango (obligatorio)")],
    account_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> EntryPageOut:
    """Lista los asientos de las cuentas propias en `[from, to)` (orden `(created_at, id)` desc)."""
    user_id = uuid.UUID(auth.user_id)
    start, end = _validate_range(from_, to)
    query = (
        select(LedgerEntry, LedgerAccount, LedgerTransaction)
        .join(LedgerAccount, LedgerEntry.account_id == LedgerAccount.id)
        .join(LedgerTransaction, LedgerEntry.transaction_id == LedgerTransaction.id)
        .where(
            LedgerAccount.owner_id == user_id,
            LedgerAccount.owner_type == "user",
            LedgerEntry.created_at >= start,
            LedgerEntry.created_at < end,
        )
    )
    if account_id is not None:
        await _owned_account(session, user_id, account_id)
        query = query.where(LedgerEntry.account_id == account_id)
    if cursor:
        created_at, row_id = decode_cursor(cursor)
        query = query.where(tuple_(LedgerEntry.created_at, LedgerEntry.id) < (_as_utc(created_at), row_id))
    query = query.order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc()).limit(limit + 1)
    rows = list((await session.execute(query)).all())

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1][0].created_at, rows[-1][0].id) if has_more and rows else None
    return EntryPageOut(
        data=[_entry_out(entry, account, transaction) for entry, account, transaction in rows],
        page=PageInfo(next_cursor=next_cursor, prev_cursor=None, has_more=has_more, limit=limit),
    )


@router.get(
    "/api/v1/ledger/statements",
    response_model=StatementPageOut,
    tags=["ledger"],
    summary="Extractos mensuales por moneda (cursor, §2.6)",
)
async def list_statements(
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_user)],
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$", max_length=3)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
) -> StatementPageOut:
    """Meses con actividad de las cuentas propias, del más reciente al más antiguo.

    El cursor codifica `(mes, moneda)`; los saldos se derivan de los asientos
    (Σcréditos - Σdébitos acumulados) sin tabla de saldos materializada (L §10).
    """
    user_id = uuid.UUID(auth.user_id)
    buckets = (
        await session.execute(
            select(
                func.date_trunc("month", LedgerEntry.created_at).label("bucket"),
                LedgerEntry.currency,
                func.count(LedgerEntry.id),
                func.coalesce(func.sum(SIGN_EXPR), 0),
            )
            .join(LedgerAccount, LedgerEntry.account_id == LedgerAccount.id)
            .where(LedgerAccount.owner_id == user_id, LedgerAccount.owner_type == "user")
            .group_by("bucket", LedgerEntry.currency)
            .order_by(LedgerEntry.currency, "bucket")
        )
    ).all()

    # saldo acumulado por moneda: running total de los deltas mensuales
    totals: dict[str, list[tuple[datetime, int, tuple[str, str]]]] = {}
    running: dict[str, Decimal] = {}
    for bucket, code, count, delta in buckets:
        previous = running.get(code, Decimal(0))
        running[code] = previous + delta
        totals.setdefault(code, []).append((bucket, count, _amounts(previous, previous + delta)))

    items = [
        StatementSummaryOut(
            statement_id=f"{bucket:%Y-%m}-{code}",
            period=StatementPeriod(
                period_from=_month_bounds(bucket.year, bucket.month)[0],
                period_to=_month_bounds(bucket.year, bucket.month)[1],
            ),
            currency=code,
            opening_balance=opening,
            closing_balance=closing,
            entries_count=count,
        )
        for code, rows in totals.items()
        for bucket, count, (opening, closing) in rows
    ]
    if currency is not None:
        items = [item for item in items if item.currency == currency]
    items.sort(key=lambda item: (item.period.period_from, item.currency), reverse=True)

    start_index = 0
    if cursor:
        cursor_month, cursor_currency = decode_period_cursor(cursor)
        for index, item in enumerate(items):
            if item.period.period_from == cursor_month and item.currency == cursor_currency:
                start_index = index + 1
                break
        else:
            raise ValidationError("cursor inválido")

    page = items[start_index : start_index + limit]
    has_more = start_index + limit < len(items)
    next_cursor = encode_period_cursor(page[-1].period.period_from, page[-1].currency) if has_more and page else None
    return StatementPageOut(
        data=page,
        page=PageInfo(next_cursor=next_cursor, prev_cursor=None, has_more=has_more, limit=limit),
    )


@router.get(
    "/api/v1/ledger/statements/{statement_id}",
    response_model=StatementOut,
    tags=["ledger"],
    summary="Extracto con asientos y saldo inicial/final (§2.6)",
)
async def get_statement(
    statement_id: str,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: str | None = None,
) -> StatementOut:
    """Detalle de un extracto mensual: `statement_id` con formato `YYYY-MM-<MONEDA>`."""
    user_id = uuid.UUID(auth.user_id)
    match = STATEMENT_ID_RE.match(statement_id)
    if match is None:
        raise ValidationError("statement_id inválido; formato esperado `YYYY-MM-<MONEDA>`")
    year, month, code = int(match.group(1)), int(match.group(2)), match.group(3)
    start, end = _month_bounds(year, month)

    opening, delta, count = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(case((LedgerEntry.created_at < start, SIGN_EXPR), else_=0)),
                    0,
                ),
                func.coalesce(
                    func.sum(case((LedgerEntry.created_at >= start, SIGN_EXPR), else_=0)),
                    0,
                ),
                func.count(case((LedgerEntry.created_at >= start, 1))),
            )
            .join(LedgerAccount, LedgerEntry.account_id == LedgerAccount.id)
            .where(
                LedgerAccount.owner_id == user_id,
                LedgerAccount.owner_type == "user",
                LedgerEntry.currency == code,
                LedgerEntry.created_at < end,
            )
        )
    ).one()

    if count == 0 and opening == 0 and delta == 0:
        raise NotFoundError("extracto")

    query = (
        select(LedgerEntry, LedgerAccount, LedgerTransaction)
        .join(LedgerAccount, LedgerEntry.account_id == LedgerAccount.id)
        .join(LedgerTransaction, LedgerEntry.transaction_id == LedgerTransaction.id)
        .where(
            LedgerAccount.owner_id == user_id,
            LedgerAccount.owner_type == "user",
            LedgerEntry.currency == code,
            LedgerEntry.created_at >= start,
            LedgerEntry.created_at < end,
        )
    )
    if cursor:
        created_at, row_id = decode_cursor(cursor)
        query = query.where(tuple_(LedgerEntry.created_at, LedgerEntry.id) < (_as_utc(created_at), row_id))
    query = query.order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc()).limit(limit + 1)
    rows = list((await session.execute(query)).all())

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor(rows[-1][0].created_at, rows[-1][0].id) if has_more and rows else None
    return StatementOut(
        statement_id=statement_id,
        period=StatementPeriod(period_from=start, period_to=end),
        currency=code,
        opening_balance=_amount(opening),
        closing_balance=_amount(opening + delta),
        entries_count=count,
        entries=[_entry_out(entry, account, transaction) for entry, account, transaction in rows],
        page=PageInfo(next_cursor=next_cursor, prev_cursor=None, has_more=has_more, limit=limit),
        as_of=utcnow(),
    )


__all__ = ["router"]
