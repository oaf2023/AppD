"""schemas — contratos HTTP del Market Data Service (Q-api-map §1.4/§2.7/§2.8, BUILD-027/028).

Precios, volúmenes y tamaños de tick se serializan como string decimal
canónico (ADR-0006); el formato numérico lo garantiza el dominio
(`domain/models.py`) antes de llegar aquí. Envelope de colección:
`{data, page}` con cursor opaco (§1.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from typing import Literal

from pydantic import BaseModel, Field

from market_data.domain.models import Timeframe

AssetClassLiteral = Literal["forex", "crypto"]
SymbolStatusLiteral = Literal["active", "paused", "delisted"]


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


class MarketStateOut(BaseModel):
    """Estado de mercado del símbolo (REQ-099, K §2)."""

    status: Literal["open", "closed", "halted"]
    reason: str
    next_open: datetime | None = None
    next_close: datetime | None = None
    as_of: datetime


class FeedBriefOut(BaseModel):
    """Estado del feed por símbolo (Q §2.7: `symbols` con estado del feed)."""

    source: str
    simulated: bool
    last_tick_ts: datetime | None = None


class SymbolOut(BaseModel):
    symbol: str
    display_name: str
    asset_class: AssetClassLiteral
    base_currency: str
    quote_currency: str
    status: SymbolStatusLiteral
    market: MarketStateOut
    feed: FeedBriefOut


class SymbolListOut(BaseModel):
    data: list[SymbolOut]
    simulated: bool
    as_of: datetime


class InstrumentOut(BaseModel):
    """Specs mínimos del instrumento (Q §2.8 `GET /instruments`)."""

    symbol: str
    display_name: str
    asset_class: AssetClassLiteral
    base_currency: str
    quote_currency: str
    status: SymbolStatusLiteral
    tick_size: str
    min_volume: str
    max_volume: str
    volume_step: str
    version: int
    valid_from: datetime


class InstrumentPageOut(BaseModel):
    data: list[InstrumentOut]
    page: PageInfo


class InstrumentDetailOut(InstrumentOut):
    """Specs mínimos + parámetros complementarios (Q §2.8 `GET /instruments/{symbol}`)."""

    pip_size: str
    contract_size: str
    price_precision: int
    market: MarketStateOut


class TradingSessionOut(BaseModel):
    weekday: int = Field(ge=0, le=6, description="ISO weekday: lunes=0 … domingo=6")
    open_utc: time
    close_utc: time
    timezone: str
    session_type: Literal["regular", "pre", "post"]
    holiday_calendar: str | None = None


class InstrumentSpecOut(BaseModel):
    """Spec completa vigente con sesiones y estado (Q §2.8 `GET .../specs`, K §2)."""

    symbol: str
    display_name: str
    asset_class: AssetClassLiteral
    status: SymbolStatusLiteral
    version: int
    valid_from: datetime
    valid_to: datetime | None = None
    tick_size: str
    pip_size: str
    contract_size: str
    min_volume: str
    max_volume: str
    volume_step: str
    price_precision: int
    margin_requirements: dict[str, str]
    fee_schedule: dict[str, str]
    swap_configuration: dict[str, str | bool]
    jurisdiction_restrictions: list[str]
    sessions: list[TradingSessionOut]
    market: MarketStateOut


__all__ = [
    "CandleOut",
    "CandlePageOut",
    "FeedBriefOut",
    "FeedStatusOut",
    "HealthOut",
    "InstrumentDetailOut",
    "InstrumentOut",
    "InstrumentPageOut",
    "InstrumentSpecOut",
    "MarketStateOut",
    "PageInfo",
    "SymbolListOut",
    "SymbolOut",
    "TickOut",
    "TickPageOut",
    "TradingSessionOut",
]
