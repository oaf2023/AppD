"""routes — endpoints del Market Data Service (Q-api-map §2.7/§2.8, BUILD-027/028).

`overview`, `healthz`/`readyz` y `market-data/symbols` son públicos
(Q §2.7 "Pública (o `read`)"; el gateway solo exige token para
`/api/v1/market-data/*` que no esté en `PUBLIC_PATHS`). Ticks, velas,
`status` e `instruments*` exigen JWT (`read` vía `require_user`).
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

from market_data.catalog import (
    active_suspension_row,
    current_spec_row,
    current_specs_for,
    get_symbol_row,
    holidays_between,
    last_tick_feed,
    list_instrument_rows,
    list_symbol_rows,
    row_to_session,
    row_to_spec,
    row_to_suspension,
    session_rows,
    spec_rows,
)
from market_data.db import get_session
from market_data.domain.models import (
    AssetClass,
    Candle,
    MarketStatus,
    SymbolStatus,
    Tick,
    Timeframe,
)
from market_data.domain.protocols import MarketDataProvider
from market_data.domain.symbol_master import OPEN_SCAN_DAYS, compute_market_status, spec_asof
from market_data.format import fmt_price as _fmt_price
from market_data.format import fmt_spec as _fmt_spec
from market_data.pagination import decode_cursor, decode_symbol_cursor, encode_symbol_cursor
from market_data.schemas import (
    CandleOut,
    CandlePageOut,
    FeedBriefOut,
    FeedStatusOut,
    HealthOut,
    InstrumentDetailOut,
    InstrumentOut,
    InstrumentPageOut,
    InstrumentSpecOut,
    MarketStateOut,
    PageInfo,
    SymbolListOut,
    SymbolOut,
    TickOut,
    TickPageOut,
    TradingSessionOut,
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
from market_data.tables import InstrumentSpecRow, SymbolRow

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


async def _market_status(
    session: AsyncSession,
    symbol: str,
    *,
    source: str,
    simulated: bool,
    now: datetime,
) -> MarketStatus:
    """Estado del mercado del símbolo: sesiones + festivos + suspensión (REQ-099)."""
    rows = await session_rows(session, symbol)
    sessions = [row_to_session(row) for row in rows]
    calendars = {item.holiday_calendar for item in sessions if item.holiday_calendar is not None}
    holidays = await holidays_between(session, calendars, now.date(), now.date() + timedelta(days=OPEN_SCAN_DAYS))
    susp_row = await active_suspension_row(session, symbol, now)
    return compute_market_status(
        symbol=symbol,
        sessions=sessions,
        suspension=row_to_suspension(susp_row) if susp_row else None,
        holidays=holidays,
        source=source,
        simulated=simulated,
        now=now,
    )


def _market_out(status: MarketStatus) -> MarketStateOut:
    return MarketStateOut(
        status=status.status,
        reason=status.reason,
        next_open=status.next_open,
        next_close=status.next_close,
        as_of=status.as_of,
    )


def _feed_out(
    feed: dict[str, tuple[datetime, str, bool]],
    row: SymbolRow,
    caps_simulated: bool,
) -> FeedBriefOut:
    last = feed.get(row.symbol)
    if last is None:
        return FeedBriefOut(source=row.source, simulated=caps_simulated, last_tick_ts=None)
    tick_ts, source, simulated = last
    return FeedBriefOut(source=source, simulated=simulated, last_tick_ts=tick_ts)


def _instrument_out(row: SymbolRow, spec: InstrumentSpecRow) -> InstrumentOut:
    return InstrumentOut(
        symbol=row.symbol,
        display_name=row.display_name,
        asset_class=row.asset_class,  # type: ignore[arg-type]  # validado por chk_symbol_asset_class
        base_currency=row.base_currency,
        quote_currency=row.quote_currency,
        status=row.status,  # type: ignore[arg-type]  # validado por chk_symbol_status
        tick_size=_fmt_spec(spec.tick_size),
        min_volume=_fmt_spec(spec.min_volume),
        max_volume=_fmt_spec(spec.max_volume),
        volume_step=_fmt_spec(spec.volume_step),
        version=spec.version,
        valid_from=spec.valid_from,
    )


# Los símbolos canónicos contienen `/` (EUR/USD): `{symbol:path}` acepta tanto
# el tramo literal como el percent-encoded `%2F` que envíen los clientes.
# `.../specs` se registra ANTES que el detalle para que `{symbol:path}` no se
# coma el sufijo (el conversor `path` es codicioso).
@router.get("/api/v1/instruments/{symbol:path}/specs", response_model=InstrumentSpecOut, tags=["instruments"])
async def instrument_specs(
    symbol: str,
    session: SessionDep,
    provider: ProviderDep,
    _auth: AuthDep,
) -> InstrumentSpecOut:
    """Spec vigente completa con sesiones y estado de mercado (Q §2.8, K §2)."""
    now = utcnow()
    row = await get_symbol_row(session, symbol)
    if row is None:
        raise NotFoundError(resource="instrumento")
    rows = await spec_rows(session, symbol)
    spec = spec_asof([row_to_spec(item) for item in rows], now)
    if spec is None:
        raise NotFoundError(resource="spec del instrumento")
    feed = await last_tick_feed(session)
    feed_out = _feed_out(feed, row, caps_simulated=provider.capabilities().simulated)
    status = await _market_status(session, symbol, source=feed_out.source, simulated=feed_out.simulated, now=now)
    sessions = [row_to_session(item) for item in await session_rows(session, symbol)]
    return InstrumentSpecOut(
        symbol=spec.symbol,
        display_name=row.display_name,
        asset_class=row.asset_class,  # type: ignore[arg-type]  # validado por chk_symbol_asset_class
        status=row.status,  # type: ignore[arg-type]  # validado por chk_symbol_status
        version=spec.version,
        valid_from=spec.valid_from,
        valid_to=spec.valid_to,
        tick_size=_fmt_spec(spec.tick_size),
        pip_size=_fmt_spec(spec.pip_size),
        contract_size=_fmt_spec(spec.contract_size),
        min_volume=_fmt_spec(spec.min_volume),
        max_volume=_fmt_spec(spec.max_volume),
        volume_step=_fmt_spec(spec.volume_step),
        price_precision=spec.price_precision,
        margin_requirements=dict(spec.margin_requirements),
        fee_schedule=dict(spec.fee_schedule),
        swap_configuration=dict(spec.swap_configuration),
        jurisdiction_restrictions=list(spec.jurisdiction_restrictions),
        sessions=[
            TradingSessionOut(
                weekday=item.weekday,
                open_utc=item.open_utc,
                close_utc=item.close_utc,
                timezone=item.timezone,
                session_type=item.session_type,
                holiday_calendar=item.holiday_calendar,
            )
            for item in sessions
        ],
        market=_market_out(status),
    )


@router.get("/api/v1/instruments/{symbol:path}", response_model=InstrumentDetailOut, tags=["instruments"])
async def instrument_detail(
    symbol: str,
    session: SessionDep,
    provider: ProviderDep,
    _auth: AuthDep,
) -> InstrumentDetailOut:
    """Specs mínimos del instrumento + estado de mercado (Q §2.8)."""
    now = utcnow()
    row = await get_symbol_row(session, symbol)
    if row is None:
        raise NotFoundError(resource="instrumento")
    spec_row = await current_spec_row(session, symbol)
    if spec_row is None:
        raise NotFoundError(resource="spec del instrumento")
    feed = await last_tick_feed(session)
    feed_out = _feed_out(feed, row, caps_simulated=provider.capabilities().simulated)
    status = await _market_status(session, symbol, source=feed_out.source, simulated=feed_out.simulated, now=now)
    base = _instrument_out(row, spec_row)
    return InstrumentDetailOut(
        **base.model_dump(),
        pip_size=_fmt_spec(spec_row.pip_size),
        contract_size=_fmt_spec(spec_row.contract_size),
        price_precision=row_to_spec(spec_row).price_precision,
        market=_market_out(status),
    )


@router.get("/api/v1/instruments", response_model=InstrumentPageOut, tags=["instruments"])
async def instruments(
    session: SessionDep,
    _auth: AuthDep,
    asset_class: AssetClass | None = Query(default=None, description="Filtrar por clase de activo"),
    status: SymbolStatus | None = Query(default=None, description="Filtrar por estado comercial"),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> InstrumentPageOut:
    """Catálogo de instrumentos con cursor y filtros por tipo/estado (Q §2.8, §1.4)."""
    after = decode_symbol_cursor(cursor) if cursor else None
    rows, has_more = await list_instrument_rows(
        session,
        asset_class=asset_class,
        status=status,
        after_symbol=after,
        limit=limit,
    )
    specs = await current_specs_for(session, [item.symbol for item in rows])
    data: list[InstrumentOut] = []
    for item in rows:
        spec = specs.get(item.symbol)
        if spec is None:
            # Invariante del catálogo: todo símbolo sembrado lleva spec vigente.
            continue
        data.append(_instrument_out(item, spec))
    next_cursor = encode_symbol_cursor(rows[-1].symbol) if has_more and rows else None
    return InstrumentPageOut(
        data=data,
        page=PageInfo(next_cursor=next_cursor, prev_cursor=None, has_more=has_more, limit=limit),
    )


@router.get("/api/v1/market-data/symbols", response_model=SymbolListOut, tags=["market-data"])
async def market_symbols(session: SessionDep, provider: ProviderDep) -> SymbolListOut:
    """Símbolos con sesión de mercado y estado del feed (Q §2.7, pública)."""
    now = utcnow()
    caps = provider.capabilities()
    rows = await list_symbol_rows(session)
    feed = await last_tick_feed(session)
    data: list[SymbolOut] = []
    for item in rows:
        feed_out = _feed_out(feed, item, caps_simulated=caps.simulated)
        status = await _market_status(
            session, item.symbol, source=feed_out.source, simulated=feed_out.simulated, now=now
        )
        data.append(
            SymbolOut(
                symbol=item.symbol,
                display_name=item.display_name,
                asset_class=item.asset_class,  # type: ignore[arg-type]  # validado por chk_symbol_asset_class
                base_currency=item.base_currency,
                quote_currency=item.quote_currency,
                status=item.status,  # type: ignore[arg-type]  # validado por chk_symbol_status
                market=_market_out(status),
                feed=feed_out,
            )
        )
    return SymbolListOut(data=data, simulated=caps.simulated, as_of=now)


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
