"""tables — tablas SQL del schema `market_data` (O-database-strategy §2/§9, BUILD-027).

- `ticks`: tick normalizado con deduplicación `(symbol, source, ts, price)`
  (K §4.4: sin `provider_seq` la dedup es por ventana temporal sobre precio/ts).
- `candles`: vela OHLC por bucket con los **huecos explícitos** de K §4.4(c):
  `gap=true` ⇒ OHLC y volumen `NULL` (nunca fabricado con el último precio);
  `gap=false` ⇒ OHLC completo con invariantes `low ≤ min(open, close)` y
  `high ≥ max(open, close)` verificadas también en CHECK.

Postgres 17 plano: hypertables/particionado quedan como DECIDIR de coste
(M §97, O §201); la retención (2 años ticks / 7 años velas) no se aplica aún.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from platform_kernel.clock import utcnow
from platform_kernel.ids import new_uuid7
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, Numeric, String, UniqueConstraint, Uuid
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


__all__ = ["AMOUNT_SCALE", "CandleRow", "TickRow"]
