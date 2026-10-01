"""routes — endpoints del Market Data Service (Q-api-map §2.7, BUILD-027).

`overview` y `healthz`/`readyz` son públicos (Q §2.7, fase 1); ticks, velas y
`status` exigen JWT (`read` vía `require_user`; el gateway exige token para
cualquier `/api/v1/market-data/*` que no sea `overview` — proxy §2.7).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from platform_contracts.market_data import MarketOverview
from platform_kernel.auth import AuthContext, require_user
from platform_kernel.clock import utcnow
from platform_kernel.errors import NotFoundError, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from market_data.db import get_session
from market_data.domain.models import PRICE_EXPONENT, Candle, Tick, Timeframe
from market_data.domain.protocols import MarketDataProvider
from market_data.pagination import decode_cursor
from market_data.schemas import (
    CandleOut,
    CandlePageOut,
    FeedStatusOut,
    HealthOut,
    PageInfo,
    TickOut,
    TickPageOut,
)
from market_data.service import MarketDataService
from market_data.store import (
    candle_cursor,
    feed_counts,
    latest_tick_row,
    list_candle_rows,
    list_tick_rows,
    row_to_candle,
    row_to_tick,
    tick_cursor,
)

router = APIRouter()

VERSION = "0.1.0"

#: Q §5: el histórico de ticks admite como máximo 24 h por request.
MAX_TICK_RANGE = timedelta(hours=24)


def _service(request: Request) -> MarketDataService:
    return request.app.state.service  # type: ignore[no-any-return]


def _provider(request: Request) -> MarketDataProvider:
    return request.app.state.market_data_provider  # type: ignore[no-any-return]


ServiceDep = Annotated[MarketDataService, Depends(_service)]
ProviderDep = Annotated[MarketDataProvider, Depends(_provider)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AuthDep = Annotated[AuthContext, Depends(require_user)]


@router.get("/healthz", response_model=HealthOut, tags=["system"])
async def healthz() -> HealthOut:
    return HealthOut(service="market-data", status="ok", version=VERSION)


@router.get("/readyz", response_model=HealthOut, tags=["system"])
async def readyz() -> HealthOut:
    # Sin dependencias locales: el proceso es la única precondición.
    # Los proveedores externos son best-effort (failover + último dato bueno).
    return HealthOut(service="market-data", status="ok", version=VERSION)


@router.get("/api/v1/market-data/overview", response_model=MarketOverview, tags=["market-data"])
async def overview(service: ServiceDep) -> MarketOverview:
    return await service.overview()


# Los símbolos canónicos contienen `/` (EUR/USD): `{symbol:path}` acepta tanto
# el tramo literal como el percent-encoded `%2F` que envíen los clientes.
@router.get("/api/v1/market-data/ticks/{symbol:path}", response_model=TickOut, tags=["market-data"])
async def latest_tick(symbol: str, session: SessionDep, _auth: AuthDep) -> TickOut:
    row = await latest_tick_row(session, symbol)
    if row is None:
        raise NotFoundError(resource="tick")
    return _tick_out(row_to_tick(row), row.id)


@router.get("/api/v1/market-data/ticks", response_model=TickPageOut, tags=["market-data"])
async def ticks_history(
    session: SessionDep,
    _auth: AuthDep,
    symbol: str = Query(min_length=1, max_length=32, description="Símbolo canónico (EUR/USD)"),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> TickPageOut:
    """Histórico de ticks (cursor, rango ≤ 24 h — Q §2.7/§5)."""
    now = utcnow()
    effective_to = to if to is not None else now
    effective_from = from_ if from_ is not None else effective_to - MAX_TICK_RANGE
    if effective_from > effective_to:
        raise ValidationError("from no puede ser posterior a to")
    if effective_to - effective_from > MAX_TICK_RANGE:
        raise ValidationError("rango máximo de 24 h por request (Q §5)")
    after = decode_cursor(cursor) if cursor else None
    rows, has_more = await list_tick_rows(
        session,
        symbol=symbol,
        from_ts=effective_from,
        to_ts=effective_to,
        cursor=after,
        limit=limit,
    )
    ticks = [row_to_tick(row) for row in rows]
    next_cursor = tick_cursor(rows[-1]) if has_more and rows else None
    return TickPageOut(
        data=[_tick_out(tick, row.id) for tick, row in zip(ticks, rows, strict=True)],
        page=PageInfo(next_cursor=next_cursor, prev_cursor=None, has_more=has_more, limit=limit),
    )


@router.get("/api/v1/market-data/candles/{symbol:path}/{timeframe}", response_model=CandlePageOut, tags=["market-data"])
async def candles(
    symbol: str,
    timeframe: Timeframe,
    session: SessionDep,
    _auth: AuthDep,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> CandlePageOut:
    """Velas OHLC (cursor + `from`/`to`; huecos `gap=true` incluidos, K §4.4(c))."""
    if from_ is not None and to is not None and from_ > to:
        raise ValidationError("from no puede ser posterior a to")
    after = decode_cursor(cursor) if cursor else None
    rows, has_more = await list_candle_rows(
        session,
        symbol=symbol,
        timeframe=timeframe,
        from_ts=from_,
        to_ts=to,
        cursor=after,
        limit=limit,
    )
    next_cursor = candle_cursor(rows[-1]) if has_more and rows else None
    return CandlePageOut(
        data=[_candle_out(row_to_candle(row), row.id) for row in rows],
        page=PageInfo(next_cursor=next_cursor, prev_cursor=None, has_more=has_more, limit=limit),
    )


@router.get("/api/v1/market-data/status", response_model=FeedStatusOut, tags=["market-data"])
async def status(
    request: Request,
    session: SessionDep,
    provider: ProviderDep,
    _auth: AuthDep,
) -> FeedStatusOut:
    """Estado del feed: simulated/real, latencia y huecos detectados (Q §2.7)."""
    counts = await feed_counts(session)
    capabilities = provider.capabilities()
    settings = request.app.state.settings
    return FeedStatusOut(
        simulated=capabilities.simulated,
        provider_id=capabilities.provider_id,
        ingest_enabled=settings.ingest_enabled,
        ticks_total=counts.ticks,
        candles_total=counts.candles,
        gaps_total=counts.gaps,
        last_tick_ts=counts.last_tick_ts,
        last_latency_ms=counts.last_latency_ms,
        as_of=utcnow(),
    )


def _fmt_price(value) -> str | None:  # type: ignore[no-untyped-def]
    """Forma canónica de precio: `Decimal` con 8 decimales (K §2, ADR-0006)."""
    if value is None:
        return None
    return str(value.quantize(PRICE_EXPONENT))


def _tick_out(tick: Tick, tick_id: uuid.UUID) -> TickOut:
    return TickOut(
        tick_id=tick_id,
        symbol=tick.symbol,
        price=_fmt_price(tick.price),
        side=tick.side,
        size=_fmt_price(tick.size),
        ts=tick.ts,
        source=tick.source,
        simulated=tick.simulated,
    )


def _candle_out(candle: Candle, candle_id: uuid.UUID) -> CandleOut:
    return CandleOut(
        candle_id=candle_id,
        symbol=candle.symbol,
        timeframe=candle.timeframe,
        ts=candle.ts,
        open=_fmt_price(candle.open),
        high=_fmt_price(candle.high),
        low=_fmt_price(candle.low),
        close=_fmt_price(candle.close),
        volume=_fmt_price(candle.volume),
        gap=candle.gap,
        source=candle.source,
        simulated=candle.simulated,
    )


__all__ = ["MAX_TICK_RANGE", "router"]
