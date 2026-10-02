"""tables — tablas SQL del schema `market_data` (O-database-strategy §2/§9, BUILD-027/028/029).

Pipeline de precios (BUILD-027):
- `ticks`: tick normalizado con deduplicación `(symbol, source, ts, price)`
  (K §4.4: sin `provider_seq` la dedup es por ventana temporal sobre precio/ts).
- `candles`: vela OHLC por bucket con los **huecos explícitos** de K §4.4(c):
  `gap=true` ⇒ OHLC y volumen `NULL` (nunca fabricado con el último precio);
  `gap=false` ⇒ OHLC completo con invariantes `low ≤ min(open, close)` y
  `high ≥ max(open, close)` verificadas también en CHECK.

Symbol master y estado de mercado (BUILD-028):
- `symbols`: identidad estable del símbolo (REQ-025).
- `instrument_specs`: specs **versionadas** (`valid_from`/`valid_to`, una sola
  versión vigente por símbolo — índice único parcial `valid_to IS NULL`).
- `trading_sessions`: ventanas UTC por día (24 h / mismo día / cruce de
  medianoche — semántica en `domain.models.TradingSession`).
- `market_suspensions`: suspensiones explícitas (`halted`, REQ-099).
- `market_holidays`: calendarios de festivos (K §2 `holiday_calendar`); el
  seed demo no declara festivos (cierres por sesión).
- `outbox`: eventos `SymbolUpdated` listos para el bus (K §4.2; drain a
  `market.symbols.changed` con reintentos/DLQ — BUILD-029, `outbox.py`).

`ticks`/`candles` **no** llevan FK a `symbols`: el histórico sobrevive a
cambios de catálogo (REQ-025: cambiar la spec no rompe datos previos).

Postgres 17 plano: hypertables/particionado quedan como DECIDIR de coste
(M §97, O §201); la retención (2 años ticks / 7 años velas) no se aplica aún.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from platform_kernel.clock import utcnow
from platform_kernel.ids import new_uuid7
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from market_data.db import SCHEMA, Base

AMOUNT_SCALE = 18
TIMEFRAME_IN = "('1m','5m','15m','1h','4h','1d')"
SIDES_IN = "('buy','sell','na')"


class TickRow(Base):
    __tablename__ = "ticks"
    __table_args__ = (
        CheckConstraint("price > 0", name="chk_tick_price_positive"),
        CheckConstraint("size IS NULL OR size >= 0", name="chk_tick_size_non_negative"),
        CheckConstraint(f"side IN {SIDES_IN}", name="chk_tick_side"),
        UniqueConstraint("symbol", "source", "ts", "price", name="uq_tick_dedup"),
        Index("ix_ticks_symbol_ts_id", "symbol", "ts", "id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    size: Mapped[Decimal | None] = mapped_column(Numeric(38, AMOUNT_SCALE))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recv_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_seq: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class CandleRow(Base):
    __tablename__ = "candles"
    __table_args__ = (
        CheckConstraint(f"timeframe IN {TIMEFRAME_IN}", name="chk_candle_timeframe"),
        CheckConstraint(
            "(gap AND open IS NULL AND high IS NULL AND low IS NULL AND close IS NULL AND volume IS NULL)"
            " OR (NOT gap AND open IS NOT NULL AND high IS NOT NULL"
            "     AND low IS NOT NULL AND close IS NOT NULL)",
            name="chk_candle_gap_nulls",
        ),
        CheckConstraint(
            "gap OR (low <= LEAST(open, close) AND high >= GREATEST(open, close) AND high >= low)",
            name="chk_candle_ohlc_invariants",
        ),
        CheckConstraint("volume IS NULL OR volume >= 0", name="chk_candle_volume_non_negative"),
        UniqueConstraint("symbol", "timeframe", "bucket_start", name="uq_candle_bucket"),
        Index("ix_candles_symbol_tf_bucket", "symbol", "timeframe", "bucket_start"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(4), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(38, AMOUNT_SCALE))
    high: Mapped[Decimal | None] = mapped_column(Numeric(38, AMOUNT_SCALE))
    low: Mapped[Decimal | None] = mapped_column(Numeric(38, AMOUNT_SCALE))
    close: Mapped[Decimal | None] = mapped_column(Numeric(38, AMOUNT_SCALE))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(38, AMOUNT_SCALE))
    #: true ⇒ bucket sin ticks observados (OHLC/volumen obligatoriamente NULL)
    gap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class SymbolRow(Base):
    """Identidad del symbol master (REQ-025, K §2, BUILD-028)."""

    __tablename__ = "symbols"
    __table_args__ = (
        CheckConstraint("asset_class IN ('forex','crypto')", name="chk_symbol_asset_class"),
        CheckConstraint("status IN ('active','paused','delisted')", name="chk_symbol_status"),
        CheckConstraint("base_currency <> quote_currency", name="chk_symbol_distinct_currencies"),
        {"schema": SCHEMA},
    )

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(8), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class InstrumentSpecRow(Base):
    """Spec negociable versionada (REQ-025: `valid_from`/`valid_to`, K §2)."""

    __tablename__ = "instrument_specs"
    __table_args__ = (
        UniqueConstraint("symbol", "version", name="uq_spec_symbol_version"),
        CheckConstraint("version >= 1", name="chk_spec_version_positive"),
        CheckConstraint("tick_size > 0", name="chk_spec_tick_size_positive"),
        CheckConstraint("pip_size > 0", name="chk_spec_pip_size_positive"),
        CheckConstraint("contract_size > 0", name="chk_spec_contract_size_positive"),
        CheckConstraint("min_volume > 0", name="chk_spec_min_volume_positive"),
        CheckConstraint("volume_step > 0", name="chk_spec_volume_step_positive"),
        CheckConstraint("max_volume >= min_volume", name="chk_spec_volume_range"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="chk_spec_valid_window"),
        # Una sola versión vigente por símbolo (REQ-025) — índice único parcial.
        Index("uq_specs_symbol_current", "symbol", unique=True, postgresql_where=text("valid_to IS NULL")),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    symbol: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.symbols.symbol", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tick_size: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    pip_size: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    contract_size: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    min_volume: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    max_volume: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    volume_step: Mapped[Decimal] = mapped_column(Numeric(38, AMOUNT_SCALE), nullable=False)
    margin_requirements: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    fee_schedule: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, default=dict)
    swap_configuration: Mapped[dict[str, str | bool]] = mapped_column(JSONB, nullable=False, default=dict)
    jurisdiction_restrictions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class TradingSessionRow(Base):
    """Ventana horaria UTC por día (K §2, BUILD-028; semántica en el dominio)."""

    __tablename__ = "trading_sessions"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="chk_session_weekday"),
        CheckConstraint("session_type IN ('regular','pre','post')", name="chk_session_type"),
        UniqueConstraint("symbol", "weekday", "open_utc", "session_type", name="uq_session_window"),
        Index("ix_sessions_symbol_weekday", "symbol", "weekday"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    symbol: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.symbols.symbol", ondelete="RESTRICT"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    open_utc: Mapped[time] = mapped_column(Time, nullable=False)
    close_utc: Mapped[time] = mapped_column(Time, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Etc/UTC")
    session_type: Mapped[str] = mapped_column(String(8), nullable=False, default="regular")
    holiday_calendar: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class MarketSuspensionRow(Base):
    """Suspensión explícita de símbolo (`halted`, REQ-099, BUILD-028)."""

    __tablename__ = "market_suspensions"
    __table_args__ = (
        CheckConstraint("code IN ('news','maintenance','breach','manual')", name="chk_suspension_code"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="chk_suspension_window"),
        Index("ix_suspensions_symbol_starts", "symbol", "starts_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    symbol: Mapped[str] = mapped_column(
        String(32), ForeignKey(f"{SCHEMA}.symbols.symbol", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class MarketHolidayRow(Base):
    """Festivo de un calendario (K §2 `holiday_calendar`; seed demo vacío)."""

    __tablename__ = "market_holidays"
    __table_args__ = (PrimaryKeyConstraint("calendar", "day", name="pk_market_holidays"), {"schema": SCHEMA})

    calendar: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class OutboxRow(Base):
    """Outbox transaccional de eventos del dominio (K §4.2, drain → Redpanda).

    Columnas de estado del relay (BUILD-029, migración `0003_outbox_relay`):
    `published_at` marca la publicación; `publish_attempts`/`next_attempt_at`/
    `last_error` gestionan reintentos con backoff; `dead_lettered_at` retiene
    el evento envenenado (DLQ). El índice parcial `ix_outbox_pending` acelera
    la consulta del relay (pendientes = sin publicar ni derivar a DLQ).
    """

    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_outbox_created_at", "created_at"),
        Index("ix_outbox_topic", "topic"),
        Index(
            "ix_outbox_pending",
            "created_at",
            postgresql_where=text("published_at IS NULL AND dead_lettered_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    topic: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(2000))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "AMOUNT_SCALE",
    "CandleRow",
    "InstrumentSpecRow",
    "MarketHolidayRow",
    "MarketSuspensionRow",
    "OutboxRow",
    "SymbolRow",
    "TickRow",
    "TradingSessionRow",
]
