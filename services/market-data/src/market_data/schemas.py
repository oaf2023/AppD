"""schemas — contratos HTTP del Market Data Service (Q-api-map §1.4/§2.7, BUILD-027).

Precios y volúmenes se serializan como string decimal canónico (ADR-0006);
el formato numérico lo garantiza el dominio (`domain/models.py`) antes de
llegar aquí. Envelope de colección: `{data, page}` con cursor opaco (§1.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from market_data.domain.models import Timeframe


class HealthOut(BaseModel):
    service: str
    status: Literal["ok", "degraded"]
    version: str


class PageInfo(BaseModel):
    """Q-api-map §1.4: cursor opaco, sin offset."""

    next_cursor: str | None = None
    prev_cursor: str | None = None
    has_more: bool = False
    limit: int = 25


class TickOut(BaseModel):
    tick_id: uuid.UUID
    symbol: str
    price: str
    side: Literal["buy", "sell", "na"]
    size: str | None = None
    ts: datetime
    source: str
    simulated: bool


class TickPageOut(BaseModel):
    data: list[TickOut]
    page: PageInfo


class CandleOut(BaseModel):
    candle_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    ts: datetime
    open: str | None = None
    high: str | None = None
    low: str | None = None
    close: str | None = None
    volume: str | None = None
    gap: bool = False
    source: str
    simulated: bool


class CandlePageOut(BaseModel):
    data: list[CandleOut]
    page: PageInfo


class FeedStatusOut(BaseModel):
    """Estado del feed (Q §2.7): simulated/real, latencia y huecos detectados."""

    simulated: bool
    provider_id: str
    ingest_enabled: bool
    ticks_total: int
    candles_total: int
    gaps_total: int
    last_tick_ts: datetime | None = None
    last_latency_ms: int | None = Field(default=None, ge=0)
    as_of: datetime


__all__ = [
    "CandleOut",
    "CandlePageOut",
    "FeedStatusOut",
    "HealthOut",
    "PageInfo",
    "TickOut",
    "TickPageOut",
]
