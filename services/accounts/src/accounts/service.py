"""service — lógica de negocio del Accounts Service.

Cuentas demo/live separadas (BUILD-020), matriz de jurisdicciones con gating
tipado (BUILD-023) y eventos `AccountCreated`/`DemoAccountCreated` emitidos en la
misma transacción (outbox transaccional, ADR-0007). Nunca se devuelve el resultado
de una operación no confirmada.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import httpx
from platform_contracts import events as ev
from platform_kernel.errors import AppError, ConflictError, NotFoundError
from platform_kernel.events import build_event
from platform_kernel.money import to_decimal
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from accounts.config import AccountsSettings
from accounts.identity_client import fetch_user_profile, service_token
from accounts.metrics import ACCOUNTS_CREATED
from accounts.models import Jurisdiction, OutboxEvent, TradingAccount
from accounts.pagination import encode_cursor
from accounts.schemas import AccountPageOut, AccountPatchIn, AccountStatus, PageInfo, UserProfile, account_out

TYPE_JURISDICTION_BLOCKED = "urn:platform:error:jurisdiction-blocked"
TYPE_LIVE_NOT_ENABLED = "urn:platform:error:live-not-enabled"

DEMO_EXISTS_DETAIL = "El usuario ya tiene una cuenta demo (una sola por usuario, BUILD-020)"


class AccountsService:
    def __init__(self, session: AsyncSession, settings: AccountsSettings) -> None:
        self.session = session
        self.settings = settings

    # ------------------------------------------------------------------ eventos

    async def _emit(
        self,
        event_type: str,
        *,
        aggregate_id: str,
        payload: dict[str, Any],
        causation_id: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        envelope = build_event(
            event_type=event_type,
            schema_version=ev.EVENT_TYPES_PHASE2[event_type],
            aggregate_id=aggregate_id,
            aggregate_type=ev.EVENT_AGGREGATE_TYPE[event_type],
            producer="accounts",
            payload=payload,
            causation_id=causation_id,
            correlation_id=correlation_id,
        )
        self.session.add(OutboxEvent(**envelope.to_outbox_row()))
        return envelope.event_id

    # ------------------------------------------------------------- jurisdicción

    async def _stored_jurisdiction(self, user_id: uuid.UUID) -> str | None:
        row = await self.session.execute(
            select(TradingAccount.jurisdiction).where(TradingAccount.user_id == user_id).limit(1)
        )
        return row.scalar_one_or_none()

    async def resolve_jurisdiction(self, user_id: uuid.UUID, *, client: httpx.AsyncClient | None = None) -> str:
        """Jurisdicción del caller: reutiliza la de sus cuentas o consulta a identity (§3)."""
        stored = await self._stored_jurisdiction(user_id)
        if stored is not None:
            return stored
        settings = self.settings
        token = service_token(
            service_name=settings.service_name,
            secret=settings.service_token_secret,
            issuer=settings.jwt_issuer,
            audience=settings.service_token_audience,
        )
        profile: UserProfile = await fetch_user_profile(
            identity_url=settings.identity_url,
            user_id=user_id,
            token=token,
            client=client,
            timeout=settings.identity_timeout_seconds,
        )
        return profile.jurisdiction

    async def enforce_jurisdiction(self, jurisdiction: str) -> None:
        """BUILD-023: la matriz versionada rechaza jurisdicciones bloqueadas con código tipado."""
        row = await self.session.get(Jurisdiction, jurisdiction)
        if row is not None and row.status == "blocked":
            raise AppError(
                403,
                TYPE_JURISDICTION_BLOCKED,
                "Jurisdicción bloqueada",
                f"La jurisdicción {jurisdiction} está bloqueada por la matriz vigente (política v{row.policy_version})",
            )

    # ---------------------------------------------------------------- creación

    async def create_account(
        self,
        *,
        user_id: uuid.UUID,
        mode: str,
        currency: str,
        jurisdiction: str,
        alias: str | None = None,
        causation_id: str | None = None,
        correlation_id: str | None = None,
    ) -> TradingAccount:
        """Crea la cuenta y emite sus eventos en la misma transacción.

        - `live` → 403 tipado (LIVE requiere KYC + flag, BUILD-020).
        - jurisdicción bloqueada → 403 tipado (BUILD-023).
        - demo duplicada → 409 (check previo + índice único parcial).
        """
        if mode == "live":
            raise AppError(
                403,
                TYPE_LIVE_NOT_ENABLED,
                "Cuenta live no habilitada",
                "La creación de cuentas LIVE requiere KYC aprobado y flag live_trading (BUILD-020; KYC en F6)",
            )
        await self.enforce_jurisdiction(jurisdiction)
        if mode == "demo":
            existing = await self.get_demo_account(user_id)
            if existing is not None:
                raise ConflictError(DEMO_EXISTS_DETAIL)

        account = TradingAccount(user_id=user_id, type=mode, currency=currency, jurisdiction=jurisdiction, alias=alias)
        self.session.add(account)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(DEMO_EXISTS_DETAIL) from None

        await self._emit(
            ev.ACCOUNT_CREATED,
            aggregate_id=str(account.id),
            payload={
                "account_id": str(account.id),
                "user_id": str(user_id),
                "type": mode,
                "currency": currency,
                "jurisdiction": jurisdiction,
                "leverage": None,
            },
            causation_id=causation_id,
            correlation_id=correlation_id,
        )
        if mode == "demo":
            await self._emit(
                ev.DEMO_ACCOUNT_CREATED,
                aggregate_id=str(account.id),
                payload={
                    "account_id": str(account.id),
                    "user_id": str(user_id),
                    "initial_balance": str(to_decimal(self.settings.demo_initial_balance)),
                    "currency": currency,
                    "expires_at": None,
                },
                causation_id=causation_id,
                correlation_id=correlation_id,
            )
        await self.session.commit()
        ACCOUNTS_CREATED.labels(mode).inc()
        return account

    # ---------------------------------------------------------------- consultas

    async def get_demo_account(self, user_id: uuid.UUID) -> TradingAccount | None:
        row = await self.session.execute(
            select(TradingAccount).where(TradingAccount.user_id == user_id, TradingAccount.type == "demo").limit(1)
        )
        return row.scalar_one_or_none()

    async def get_account(self, *, user_id: uuid.UUID, account_id: uuid.UUID) -> TradingAccount:
        account = await self.session.get(TradingAccount, account_id)
        if account is None or account.user_id != user_id:
            # §1.7.3 (BOLA): recurso ajeno o inexistente → misma respuesta 404
            raise NotFoundError("cuenta")
        return account

    async def get_account_internal(self, account_id: uuid.UUID) -> TradingAccount:
        account = await self.session.get(TradingAccount, account_id)
        if account is None:
            raise NotFoundError("cuenta")
        return account

    async def list_accounts(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        cursor: tuple[datetime, uuid.UUID] | None = None,
        status: AccountStatus | None = None,
        currency: str | None = None,
    ) -> AccountPageOut:
        query = select(TradingAccount).where(TradingAccount.user_id == user_id)
        if status is not None:
            query = query.where(TradingAccount.status == status)
        if currency is not None:
            query = query.where(TradingAccount.currency == currency)
        if cursor is not None:
            created_at, row_id = cursor
            query = query.where(tuple_(TradingAccount.created_at, TradingAccount.id) < (created_at, row_id))
        query = query.order_by(TradingAccount.created_at.desc(), TradingAccount.id.desc()).limit(limit + 1)
        rows = list((await self.session.execute(query)).scalars())

        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
        return AccountPageOut(
            data=[account_out(row) for row in rows],
            page=PageInfo(next_cursor=next_cursor, prev_cursor=None, has_more=has_more, limit=limit),
        )

    async def patch_account(self, *, user_id: uuid.UUID, account_id: uuid.UUID, body: AccountPatchIn) -> TradingAccount:
        account = await self.get_account(user_id=user_id, account_id=account_id)
        if "alias" in body.model_fields_set:
            account.alias = body.alias
        await self.session.commit()
        return account


__all__ = [
    "DEMO_EXISTS_DETAIL",
    "TYPE_JURISDICTION_BLOCKED",
    "TYPE_LIVE_NOT_ENABLED",
    "AccountsService",
]
