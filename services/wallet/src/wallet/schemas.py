"""schemas - contratos HTTP del Wallet Service (Q-api-map §2.5, BUILD-019/021/022).

Los montos se serializan como string decimal canónico (ADR-0006); el formato
numerico se valida con `platform_kernel.money.to_decimal` en `service.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TYPE_VALIDATION = "urn:platform:error:validation"
TYPE_INSUFFICIENT = "urn:platform:error:insufficient-balance"


class HealthOut(BaseModel):
    service: str
    status: str


class ReadyOut(BaseModel):
    status: str


class PageInfo(BaseModel):
    """Q-api-map §1.4: cursor opaco, sin offset."""

    next_cursor: str | None = None
    prev_cursor: str | None = None
    has_more: bool = False
    limit: int = 25


class ReconciliationOut(BaseModel):
    """Estado de la última comparación wallet↔ledger (BUILD-019)."""

    stale: bool
    checked_at: datetime | None = None


class BalanceOut(BaseModel):
    currency: str
    available: str
    reserved: str
    stale: bool = False
    reconciled_at: datetime | None = None


class BalanceListOut(BaseModel):
    data: list[BalanceOut]
    as_of: datetime
    reconciliation: ReconciliationOut


class WalletBalanceOut(BalanceOut):
    as_of: datetime


class MovementOut(BaseModel):
    movement_id: uuid.UUID
    currency: str
    delta: str
    direction: Literal["D", "C"]
    tx_type: str
    ledger_transaction_id: uuid.UUID
    occurred_at: datetime
    created_at: datetime


class MovementPageOut(BaseModel):
    data: list[MovementOut]
    page: PageInfo


class TransferIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: str = Field(min_length=1, description="Decimal canónico (punto decimal, sin separadores)")
    currency: str = Field(pattern="^[A-Z]{3}$", description="ISO 4217, debe coincidir con ambas cuentas")


class TransferOut(BaseModel):
    transfer_id: uuid.UUID
    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: str
    currency: str
    status: Literal["posted"] = "posted"
    occurred_at: datetime


class ConversionRateOut(BaseModel):
    base: str
    quote: str
    rate: str
    source: str
    as_of: datetime


class ConversionRatesOut(BaseModel):
    data: list[ConversionRateOut]
    source: str | None = None
    as_of: datetime | None = None


class AccountRef(BaseModel):
    """Subconjunto de `accounts.AccountOut` que necesita wallet para validar transferencias."""

    account_id: uuid.UUID
    user_id: uuid.UUID
    type: str
    currency: str
    status: str


__all__ = [
    "TYPE_INSUFFICIENT",
    "TYPE_VALIDATION",
    "AccountRef",
    "BalanceListOut",
    "BalanceOut",
    "ConversionRateOut",
    "ConversionRatesOut",
    "HealthOut",
    "MovementOut",
    "MovementPageOut",
    "PageInfo",
    "ReadyOut",
    "ReconciliationOut",
    "TransferIn",
    "TransferOut",
    "WalletBalanceOut",
]
