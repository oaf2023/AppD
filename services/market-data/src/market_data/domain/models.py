"""models — tipos canónicos de mercado (K §2) sin floats (ADR-0006).

Todo precio es `Decimal` con 8 decimales; los tiempos son UTC con zona horaria.
El tipo `ReferenceQuote` (valor único de portada) vive en `protocols.py` como
deuda conocida de decimalización; aquí está la forma canónica de trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

AssetClass = Literal["forex", "crypto"]
MarketStatusKind = Literal["open", "closed", "halted"]
TickSide = Literal["buy", "sell", "na"]
Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d"]

PRICE_EXPONENT = Decimal("0.00000001")

#: Q-api-map §2.7 / R-websocket-map §4.1: timeframes canónicos aceptados por la API.
TIMEFRAMES: tuple[Timeframe, ...] = ("1m", "5m", "15m", "1h", "4h", "1d")
TICK_SIDES: tuple[TickSide, ...] = ("buy", "sell", "na")


class CanonicalDataError(ValueError):
    """Valor fuera del contrato canónico (K §2): tipo, rango o invariante violado."""


def _require_price(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise CanonicalDataError(f"{name}: se exige Decimal (ADR-0006); llegó {type(value).__name__}")
    if value <= 0:
        raise CanonicalDataError(f"{name}: debe ser > 0; llegó {value}")


def _require_aware(name: str, value: datetime) -> None:
    if value.utcoffset() is None:
        raise CanonicalDataError(f"{name}: debe ser un timestamp con zona horaria (UTC)")


def _require_complete_price(name: str, value: Decimal | None) -> Decimal:
    """OHLC obligatorio cuando `gap=false`; devuelve el valor estrechado."""
    if value is None:
        raise CanonicalDataError(f"{name}: obligatorio cuando gap=false")
    _require_price(name, value)
    return value


@dataclass(frozen=True, slots=True)
class Quote:
    """Cotización canónica (K §2): `bid ≤ ask` obligatorio; `spread` derivado."""

    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    ts: datetime
    source: str
    simulated: bool
    stale: bool = False

    def __post_init__(self) -> None:
        if not self.symbol:
            raise CanonicalDataError("symbol: no puede estar vacío")
        if not self.source:
            raise CanonicalDataError("source: no puede estar vacío")
        _require_price("bid", self.bid)
        _require_price("ask", self.ask)
        _require_price("last", self.last)
        if self.bid > self.ask:
            raise CanonicalDataError(f"bid <= ask obligatorio (K §2); llegó bid={self.bid} ask={self.ask}")
        _require_aware("ts", self.ts)

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class Ticker:
    """Quote + estadísticas 24h (K §2): solo si el originario las provee; nunca estimadas."""

    quote: Quote
    volume_24h: Decimal | None = None
    change_pct: Decimal | None = None
    high_24h: Decimal | None = None
    low_24h: Decimal | None = None

    def __post_init__(self) -> None:
        if self.volume_24h is not None:
            if not isinstance(self.volume_24h, Decimal):
                raise CanonicalDataError("volume_24h: se exige Decimal (ADR-0006)")
            if self.volume_24h < 0:
                raise CanonicalDataError(f"volume_24h: no puede ser negativo; llegó {self.volume_24h}")
        for name, value in (("high_24h", self.high_24h), ("low_24h", self.low_24h)):
            if value is not None:
                _require_price(name, value)


@dataclass(frozen=True, slots=True)
class MarketStatus:
    """Estado de mercado (K §2): `halted` (suspensión) ≠ `closed` (horario) ≠ `stale` (calidad)."""

    symbol: str | None
    status: MarketStatusKind
    reason: str
    as_of: datetime
    source: str
    simulated: bool
    next_open: datetime | None = None
    next_close: datetime | None = None

    def __post_init__(self) -> None:
        if self.status not in ("open", "closed", "halted"):
            raise CanonicalDataError(f"status: valor desconocido {self.status!r}")
        if not self.reason:
            raise CanonicalDataError("reason: no puede estar vacío")
        if not self.source:
            raise CanonicalDataError("source: no puede estar vacío")
        _require_aware("as_of", self.as_of)
        if self.next_open is not None:
            _require_aware("next_open", self.next_open)
        if self.next_close is not None:
            _require_aware("next_close", self.next_close)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Capacidades declaradas del proveedor (K §1.1): clases, granularidad, REST/WS, rate limits."""

    provider_id: str
    asset_classes: tuple[AssetClass, ...]
    granularity: str
    supports_rest: bool
    supports_ws: bool
    simulated: bool
    rate_limit: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise CanonicalDataError("provider_id: no puede estar vacío")
        if not self.asset_classes:
            raise CanonicalDataError("asset_classes: al menos una clase de activo")
        if not self.granularity:
            raise CanonicalDataError("granularity: no puede estar vacío")


@dataclass(frozen=True, slots=True)
class Tick:
    """Tick canónico de mercado (K §2): precio `Decimal`, `size` opcional, UTC con zona.

    `side="na"` cuando el originario no informa dirección; `provider_seq=None`
    cuando no hay secuencia (deduplicación por ventana temporal, K §4.4).
    """

    symbol: str
    price: Decimal
    side: TickSide
    size: Decimal | None
    ts: datetime
    recv_ts: datetime
    source: str
    simulated: bool
    provider_seq: int | None = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise CanonicalDataError("symbol: no puede estar vacío")
        if not self.source:
            raise CanonicalDataError("source: no puede estar vacío")
        _require_price("price", self.price)
        if self.side not in TICK_SIDES:
            raise CanonicalDataError(f"side: valor desconocido {self.side!r}")
        if self.size is not None:
            if not isinstance(self.size, Decimal):
                raise CanonicalDataError(f"size: se exige Decimal (ADR-0006); llegó {type(self.size).__name__}")
            if self.size < 0:
                raise CanonicalDataError(f"size: no puede ser negativo; llegó {self.size}")
        _require_aware("ts", self.ts)
        _require_aware("recv_ts", self.recv_ts)
        if self.provider_seq is not None and self.provider_seq < 0:
            raise CanonicalDataError(f"provider_seq: no puede ser negativo; llegó {self.provider_seq}")


@dataclass(frozen=True, slots=True)
class Candle:
    """Vela OHLC canónica (K §2, REQ-028): invariantes H/L y huecos explícitos.

    `gap=True` ⇒ OHLC y volumen **todos** `None` (K §4.4(c): un bucket sin ticks
    se marca como hueco y nunca se fabrica con el último precio). `gap=False` ⇒
    OHLC completo y `low ≤ min(open, close) ≤ max(open, close) ≤ high`;
    `volume` es `None` si algún tick del bucket carece de tamaño conocido.
    """

    symbol: str
    timeframe: Timeframe
    ts: datetime
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: Decimal | None
    gap: bool
    source: str
    simulated: bool

    def __post_init__(self) -> None:
        if not self.symbol:
            raise CanonicalDataError("symbol: no puede estar vacío")
        if not self.source:
            raise CanonicalDataError("source: no puede estar vacío")
        if self.timeframe not in TIMEFRAMES:
            raise CanonicalDataError(f"timeframe: valor desconocido {self.timeframe!r}")
        _require_aware("ts", self.ts)
        if self.gap:
            for name in ("open", "high", "low", "close", "volume"):
                if getattr(self, name) is not None:
                    raise CanonicalDataError(f"gap=true exige {name}=null (K §4.4(c): nunca fabricado)")
            return
        open_v = _require_complete_price("open", self.open)
        high_v = _require_complete_price("high", self.high)
        low_v = _require_complete_price("low", self.low)
        close_v = _require_complete_price("close", self.close)
        if low_v > min(open_v, close_v):
            raise CanonicalDataError(
                f"low <= min(open, close) obligatorio (REQ-028); llegó low={low_v} open={open_v} close={close_v}"
            )
        if high_v < max(open_v, close_v):
            raise CanonicalDataError(
                f"high >= max(open, close) obligatorio (REQ-028); llegó high={high_v} open={open_v} close={close_v}"
            )
        if self.volume is not None:
            if not isinstance(self.volume, Decimal):
                raise CanonicalDataError("volume: se exige Decimal (ADR-0006)")
            if self.volume < 0:
                raise CanonicalDataError(f"volume: no puede ser negativo; llegó {self.volume}")


__all__ = [
    "PRICE_EXPONENT",
    "TICK_SIDES",
    "TIMEFRAMES",
    "AssetClass",
    "Candle",
    "CanonicalDataError",
    "MarketStatus",
    "MarketStatusKind",
    "ProviderCapabilities",
    "Quote",
    "Tick",
    "TickSide",
    "Ticker",
    "Timeframe",
]
