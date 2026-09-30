"""schemas — contratos de API del Accounts Service (Q-api-map §2.4, §1.4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from accounts.models import TradingAccount

AccountType = Literal["demo", "live"]
AccountStatus = Literal["active", "suspended", "closed"]


class HealthOut(BaseModel):
    service: str = "accounts"
    status: str = "ok"


class ReadyOut(BaseModel):
    status: str = "ready"


class AccountOut(BaseModel):
    account_id: uuid.UUID
    user_id: uuid.UUID
    type: AccountType
    currency: str
    jurisdiction: str
    status: AccountStatus
    alias: str | None = None
    leverage: int | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


def account_out(account: TradingAccount) -> AccountOut:
    return AccountOut(
        account_id=account.id,
        user_id=account.user_id,
        type=account.type,  # type: ignore[arg-type]
        currency=account.currency,
        jurisdiction=account.jurisdiction,
        status=account.status,  # type: ignore[arg-type]
        alias=account.alias,
        leverage=account.leverage,
        created_at=account.created_at,
        updated_at=account.updated_at,
        closed_at=account.closed_at,
    )


class PageInfo(BaseModel):
    """Q-api-map §1.4: cursor sobre `(created_at DESC, id DESC)`; sin offset."""

    next_cursor: str | None = None
    prev_cursor: str | None = None
    has_more: bool = False
    limit: int = 25


class AccountPageOut(BaseModel):
    data: list[AccountOut]
    page: PageInfo


class AccountCreateIn(BaseModel):
    """POST /api/v1/accounts — solo `demo` se acepta en F2 (LIVE: BUILD-020/§2.4)."""

    mode: AccountType = "demo"
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$", max_length=3)
    alias: str | None = Field(default=None, max_length=64)


class AccountPatchIn(BaseModel):
    """PATCH /api/v1/accounts/{id} — ajustes permitidos (§2.4): alias."""

    alias: str | None = Field(default=None, max_length=64)


class ReloadDemoOut(BaseModel):
    """POST /api/v1/accounts/{id}/reload-demo — recarga de la demo (BUILD-020).

    El saldo real lo aplica ledger vía `DemoBalanceReset` (#17); aquí se
    devuelve el objetivo y el saldo previo leído de la fuente de verdad.
    """

    account_id: uuid.UUID
    currency: str
    previous_balance: str
    new_balance: str
    status: Literal["scheduled"] = "scheduled"
    event_id: str


class UserProfile(BaseModel):
    """Perfil mínimo devuelto por `identity` en `GET /internal/v1/users/{id}` (§3)."""

    user_id: uuid.UUID
    status: str
    jurisdiction: str
    email_verified: bool = False


__all__ = [
    "AccountCreateIn",
    "AccountOut",
    "AccountPageOut",
    "AccountPatchIn",
    "AccountStatus",
    "AccountType",
    "HealthOut",
    "PageInfo",
    "ReadyOut",
    "ReloadDemoOut",
    "UserProfile",
    "account_out",
]
