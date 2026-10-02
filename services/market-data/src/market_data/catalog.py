"""catalog — consultas del symbol master versionado (REQ-025/REQ-099, BUILD-028).

Capa de datos del catálogo: símbolos, specs `valid_from`/`valid_to`, sesiones
UTC, suspensiones, festivos y outbox de `SymbolUpdated` (K §4.2 — el drain a
`market.symbols.changed` vive en `market_data.outbox.py`, BUILD-029). Los
convertidores fila→dominio garantizan `Decimal`
y timestamps con zona (ADR-0006).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from platform_kernel.clock import utcnow
from platform_kernel.context import get_correlation_id
from platform_kernel.ids import new_uuid7
from sqlalchemy import or_, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from market_data.domain.models import (
    InstrumentSpec,
    Suspension,
    SymbolMetadata,
    TradingSession,
)
from market_data.tables import (
    InstrumentSpecRow,
    MarketHolidayRow,
    MarketSuspensionRow,
    OutboxRow,
    SymbolRow,
    TickRow,
    TradingSessionRow,
)

#: Topic de invalidación de cache del catálogo (K §4.5, retención 30 días).
SYMBOLS_CHANGED_TOPIC = "market.symbols.changed"


def row_to_symbol(row: SymbolRow) -> SymbolMetadata:
    return SymbolMetadata(
        symbol=row.symbol,
        display_name=row.display_name,
        asset_class=row.asset_class,  # type: ignore[arg-type]  # validado por chk_symbol_asset_class
        base_currency=row.base_currency,
        quote_currency=row.quote_currency,
        status=row.status,  # type: ignore[arg-type]  # validado por chk_symbol_status
        source=row.source,
    )


def row_to_spec(row: InstrumentSpecRow) -> InstrumentSpec:
    return InstrumentSpec(
        symbol=row.symbol,
        version=row.version,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        tick_size=row.tick_size,
        pip_size=row.pip_size,
        contract_size=row.contract_size,
        min_volume=row.min_volume,
        max_volume=row.max_volume,
        volume_step=row.volume_step,
        margin_requirements=dict(row.margin_requirements),
        fee_schedule=dict(row.fee_schedule),
        swap_configuration=dict(row.swap_configuration),
        jurisdiction_restrictions=tuple(row.jurisdiction_restrictions),
    )


def row_to_session(row: TradingSessionRow) -> TradingSession:
    return TradingSession(
        symbol=row.symbol,
        weekday=row.weekday,
        open_utc=row.open_utc,  # type: ignore[arg-type]  # columna Time (naive UTC)
        close_utc=row.close_utc,  # type: ignore[arg-type]
        timezone=row.timezone,
        session_type=row.session_type,  # type: ignore[arg-type]  # validado por chk_session_type
        holiday_calendar=row.holiday_calendar,
    )


def row_to_suspension(row: MarketSuspensionRow) -> Suspension:
    return Suspension(
        symbol=row.symbol,
        code=row.code,  # type: ignore[arg-type]  # validado por chk_suspension_code
        reason=row.reason,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
    )


async def list_symbol_rows(session: AsyncSession) -> list[SymbolRow]:
    stmt = select(SymbolRow).order_by(SymbolRow.symbol.asc())
    return list((await session.execute(stmt)).scalars())


async def get_symbol_row(session: AsyncSession, symbol: str) -> SymbolRow | None:
    stmt = select(SymbolRow).where(SymbolRow.symbol == symbol)
    return (await session.execute(stmt)).scalars().first()


async def spec_rows(session: AsyncSession, symbol: str) -> list[InstrumentSpecRow]:
    stmt = select(InstrumentSpecRow).where(InstrumentSpecRow.symbol == symbol).order_by(InstrumentSpecRow.version.asc())
    return list((await session.execute(stmt)).scalars())


async def current_spec_row(session: AsyncSession, symbol: str) -> InstrumentSpecRow | None:
    stmt = select(InstrumentSpecRow).where(InstrumentSpecRow.symbol == symbol, InstrumentSpecRow.valid_to.is_(None))
    return (await session.execute(stmt)).scalars().first()


async def current_specs_for(session: AsyncSession, symbols: Sequence[str]) -> dict[str, InstrumentSpecRow]:
    """Specs vigentes de `symbols` en una sola consulta `{symbol: row}`."""
    if not symbols:
        return {}
    stmt = select(InstrumentSpecRow).where(InstrumentSpecRow.symbol.in_(symbols), InstrumentSpecRow.valid_to.is_(None))
    return {row.symbol: row for row in (await session.execute(stmt)).scalars()}


async def session_rows(session: AsyncSession, symbol: str) -> list[TradingSessionRow]:
    stmt = (
        select(TradingSessionRow)
        .where(TradingSessionRow.symbol == symbol)
        .order_by(TradingSessionRow.weekday.asc(), TradingSessionRow.open_utc.asc())
    )
    return list((await session.execute(stmt)).scalars())


async def active_suspension_row(session: AsyncSession, symbol: str, now: datetime) -> MarketSuspensionRow | None:
    stmt = (
        select(MarketSuspensionRow)
        .where(
            MarketSuspensionRow.symbol == symbol,
            MarketSuspensionRow.starts_at <= now,
            or_(MarketSuspensionRow.ends_at.is_(None), MarketSuspensionRow.ends_at > now),
        )
        .order_by(MarketSuspensionRow.starts_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def holidays_between(
    session: AsyncSession,
    calendars: set[str],
    start: date,
    end: date,
) -> dict[date, str]:
    """Festivos `{día: etiqueta}` de los calendarios dados en `[start, end]`."""
    if not calendars:
        return {}
    stmt = select(MarketHolidayRow.day, MarketHolidayRow.label).where(
        MarketHolidayRow.calendar.in_(calendars),
        MarketHolidayRow.day >= start,
        MarketHolidayRow.day <= end,
    )
    return {day: label for day, label in (await session.execute(stmt)).all()}


async def list_instrument_rows(
    session: AsyncSession,
    *,
    asset_class: str | None,
    status: str | None,
    after_symbol: str | None,
    limit: int,
) -> tuple[list[SymbolRow], bool]:
    """Catálogo ordenado por `symbol ASC` con keyset sobre el cursor (Q §1.4)."""
    conditions = []
    if asset_class is not None:
        conditions.append(SymbolRow.asset_class == asset_class)
    if status is not None:
        conditions.append(SymbolRow.status == status)
    if after_symbol is not None:
        conditions.append(SymbolRow.symbol > after_symbol)
    stmt = select(SymbolRow).where(*conditions).order_by(SymbolRow.symbol.asc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars())
    has_more = len(rows) > limit
    return rows[:limit], has_more


async def last_tick_feed(session: AsyncSession) -> dict[str, tuple[datetime, str, bool]]:
    """Último tick por símbolo `{symbol: (ts, source, simulated)}` (DISTINCT ON)."""
    stmt = (
        select(TickRow)
        .ext(postgresql.distinct_on(TickRow.symbol))
        .order_by(TickRow.symbol.asc(), TickRow.ts.desc(), TickRow.id.desc())
    )
    return {row.symbol: (row.ts, row.source, row.simulated) for row in (await session.execute(stmt)).scalars()}


async def activate_spec_version(session: AsyncSession, spec: InstrumentSpec) -> InstrumentSpecRow:
    """Cierra la versión vigente en `spec.valid_from` e inserta la nueva (REQ-025)."""
    if spec.valid_to is not None:
        raise ValueError("la nueva versión se inserta vigente (valid_to=None)")
    current = await current_spec_row(session, spec.symbol)
    if current is not None:
        if current.version >= spec.version:
            raise ValueError(f"la versión nueva ({spec.version}) debe superar a la vigente ({current.version})")
        current.valid_to = spec.valid_from
    row = InstrumentSpecRow(
        symbol=spec.symbol,
        version=spec.version,
        valid_from=spec.valid_from,
        valid_to=spec.valid_to,
        tick_size=spec.tick_size,
        pip_size=spec.pip_size,
        contract_size=spec.contract_size,
        min_volume=spec.min_volume,
        max_volume=spec.max_volume,
        volume_step=spec.volume_step,
        margin_requirements=dict(spec.margin_requirements),
        fee_schedule=dict(spec.fee_schedule),
        swap_configuration=dict(spec.swap_configuration),
        jurisdiction_restrictions=list(spec.jurisdiction_restrictions),
    )
    session.add(row)
    await session.flush()
    return row


def _symbol_updated_payload(symbol: str, *, event: str, code: str, now: datetime) -> dict[str, Any]:
    """Envelope canónico P §1 para `SymbolUpdated` (productor `market-data`)."""
    event_id = new_uuid7()
    return {
        "event_id": str(event_id),
        "event_type": "SymbolUpdated",
        "schema_version": 1,
        "aggregate_id": symbol,
        "aggregate_type": "Symbol",
        "timestamp": now.isoformat(),
        "correlation_id": get_correlation_id(),
        "causation_id": None,
        "producer": "market-data",
        "payload": {"symbol": symbol, "event": event, "code": code},
    }


async def insert_suspension(
    session: AsyncSession,
    *,
    symbol: str,
    code: str,
    reason: str,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> MarketSuspensionRow:
    """Registra una suspensión y su evento `SymbolUpdated` en la misma transacción."""
    now = starts_at or utcnow()
    row = MarketSuspensionRow(symbol=symbol, code=code, reason=reason, starts_at=now, ends_at=ends_at)
    session.add(row)
    await session.flush()
    session.add(
        OutboxRow(
            topic=SYMBOLS_CHANGED_TOPIC,
            event_type="SymbolUpdated",
            payload=_symbol_updated_payload(symbol, event="suspended", code=code, now=now),
        )
    )
    await session.flush()
    return row


async def outbox_rows(session: AsyncSession, *, event_type: str | None = None) -> list[OutboxRow]:
    conditions = [] if event_type is None else [OutboxRow.event_type == event_type]
    stmt = select(OutboxRow).where(*conditions).order_by(OutboxRow.created_at.asc(), OutboxRow.id.asc())
    return list((await session.execute(stmt)).scalars())


async def active_suspensions(session: AsyncSession, symbols: Sequence[str], now: datetime) -> dict[str, Suspension]:
    """Suspensiones vigentes de `symbols` en `now` `{symbol: Suspension}`."""
    if not symbols:
        return {}
    stmt = select(MarketSuspensionRow).where(
        MarketSuspensionRow.symbol.in_(symbols),
        MarketSuspensionRow.starts_at <= now,
        or_(MarketSuspensionRow.ends_at.is_(None), MarketSuspensionRow.ends_at > now),
    )
    return {row.symbol: row_to_suspension(row) for row in (await session.execute(stmt)).scalars()}


__all__ = [
    "SYMBOLS_CHANGED_TOPIC",
    "activate_spec_version",
    "active_suspension_row",
    "active_suspensions",
    "current_spec_row",
    "current_specs_for",
    "get_symbol_row",
    "holidays_between",
    "insert_suspension",
    "last_tick_feed",
    "list_instrument_rows",
    "list_symbol_rows",
    "outbox_rows",
    "row_to_session",
    "row_to_spec",
    "row_to_suspension",
    "row_to_symbol",
    "session_rows",
    "spec_rows",
]
