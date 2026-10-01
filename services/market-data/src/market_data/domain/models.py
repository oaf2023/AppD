"""models — tipos canónicos de mercado (K §2) sin floats (ADR-0006).

Todo precio es `Decimal` con 8 decimales; los tiempos son UTC con zona horaria.
El tipo `ReferenceQuote` (valor único de portada) vive en `protocols.py` como
deuda conocida de decimalización; aquí está la forma canónica de trading.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from typing import Literal

AssetClass = Literal["forex", "crypto"]
MarketStatusKind = Literal["open", "closed", "halted"]
SessionType = Literal["regular", "pre", "post"]
SymbolStatus = Literal["active", "paused", "delisted"]
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


@dataclass(frozen=True, slots=True)
class SymbolMetadata:
    """Identidad del símbolo en el symbol master (K §2, REQ-025, BUILD-028).

    Las especificaciones negociables viven en `InstrumentSpec` versionado;
    aquí solo la identidad estable (símbolo canónico con `/`, clase, divisas,
    estado comercial y fuente declarada — K §3.1: un símbolo = asset_class +
    calendario + fuente de precio).
    """

    symbol: str
    display_name: str
    asset_class: AssetClass
    base_currency: str
    quote_currency: str
    status: SymbolStatus
    source: str

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol.strip() != self.symbol:
            raise CanonicalDataError("symbol: no puede estar vacío ni con espacios")
        if not self.display_name:
            raise CanonicalDataError("display_name: no puede estar vacío")
        if self.asset_class not in ("forex", "crypto"):
            raise CanonicalDataError(f"asset_class: valor desconocido {self.asset_class!r}")
        if not self.base_currency or not self.quote_currency:
            raise CanonicalDataError("base_currency/quote_currency: obligatorios")
        if self.status not in ("active", "paused", "delisted"):
            raise CanonicalDataError(f"status: valor desconocido {self.status!r}")
        if not self.source:
            raise CanonicalDataError("source: no puede estar vacío")


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """Spec negociable versionada de un símbolo (K §2, REQ-025, BUILD-028).

    Versionado `valid_from`/`valid_to` (`valid_to=None` ⇒ versión vigente);
    el redondeo de precios se deriva de `tick_size` (K §2 → `price_precision`),
    nunca se almacena. Los campos `*_requirements`/`fee_schedule`/`swap` son
    JSON declarativo; en el catálogo demo van etiquetados como `mode: demo`.
    """

    symbol: str
    version: int
    valid_from: datetime
    valid_to: datetime | None
    tick_size: Decimal
    pip_size: Decimal
    contract_size: Decimal
    min_volume: Decimal
    max_volume: Decimal
    volume_step: Decimal
    margin_requirements: Mapping[str, str] = field(default_factory=dict)
    fee_schedule: Mapping[str, str] = field(default_factory=dict)
    swap_configuration: Mapping[str, str | bool] = field(default_factory=dict)
    jurisdiction_restrictions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.symbol:
            raise CanonicalDataError("symbol: no puede estar vacío")
        if self.version < 1:
            raise CanonicalDataError(f"version: debe ser >= 1; llegó {self.version}")
        _require_aware("valid_from", self.valid_from)
        if self.valid_to is not None:
            _require_aware("valid_to", self.valid_to)
            if self.valid_to <= self.valid_from:
                raise CanonicalDataError("valid_to: debe ser posterior a valid_from")
        for name in ("tick_size", "pip_size", "contract_size", "min_volume", "volume_step"):
            value: Decimal = getattr(self, name)
            if not isinstance(value, Decimal):
                raise CanonicalDataError(f"{name}: se exige Decimal (ADR-0006)")
            if value <= 0:
                raise CanonicalDataError(f"{name}: debe ser > 0; llegó {value}")
        if not isinstance(self.max_volume, Decimal) or self.max_volume < self.min_volume:
            raise CanonicalDataError(
                f"max_volume: debe ser Decimal y >= min_volume; llegó {self.max_volume} < {self.min_volume}"
            )

    @property
    def price_precision(self) -> int:
        """Decimales de precio derivados de `tick_size` (K §2: redondeo por tick)."""
        exponent = self.tick_size.normalize().as_tuple().exponent
        return max(0, -int(exponent))

    @property
    def is_current(self) -> bool:
        return self.valid_to is None


@dataclass(frozen=True, slots=True)
class TradingSession:
    """Ventana horaria de un símbolo (K §2, BUILD-028).

    Semántica de las ventanas (horas **UTC**, `timezone` es la etiqueta IANA
    declaratoria — K §2 `open_utc`/`close_utc`):
    - `open == close` ⇒ ventana de 24 h (crypto 24/7);
    - `open < close`  ⇒ ventana dentro del mismo día UTC;
    - `open > close`  ⇒ ventana que cruza medianoche (termina al día siguiente).
    `weekday` usa la convención ISO/Python: lunes=0 … domingo=6.
    """

    symbol: str
    weekday: int
    open_utc: time
    close_utc: time
    timezone: str
    session_type: SessionType
    holiday_calendar: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.weekday <= 6:
            raise CanonicalDataError(f"weekday: debe estar en [0, 6]; llegó {self.weekday}")
        if self.open_utc.tzinfo is not None or self.close_utc.tzinfo is not None:
            raise CanonicalDataError("open_utc/close_utc: deben ser horas sin zona (ya están en UTC)")
        if not self.timezone:
            raise CanonicalDataError("timezone: obligatoria (IANA)")
        if self.session_type not in ("regular", "pre", "post"):
            raise CanonicalDataError(f"session_type: valor desconocido {self.session_type!r}")


@dataclass(frozen=True, slots=True)
class Suspension:
    """Suspensión explícita de un símbolo (K §2 `halted`, REQ-099, BUILD-028)."""

    symbol: str
    code: Literal["news", "maintenance", "breach", "manual"]
    reason: str
    starts_at: datetime
    ends_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.symbol:
            raise CanonicalDataError("symbol: no puede estar vacío")
        if self.code not in ("news", "maintenance", "breach", "manual"):
            raise CanonicalDataError(f"code: valor desconocido {self.code!r}")
        _require_aware("starts_at", self.starts_at)
        if self.ends_at is not None:
            _require_aware("ends_at", self.ends_at)
            if self.ends_at <= self.starts_at:
                raise CanonicalDataError("ends_at: debe ser posterior a starts_at")


__all__ = [
    "PRICE_EXPONENT",
    "TICK_SIDES",
    "TIMEFRAMES",
    "AssetClass",
    "Candle",
    "CanonicalDataError",
    "InstrumentSpec",
    "MarketStatus",
    "MarketStatusKind",
    "ProviderCapabilities",
    "Quote",
    "SessionType",
    "Suspension",
    "SymbolMetadata",
    "SymbolStatus",
    "Tick",
    "TickSide",
    "Ticker",
    "Timeframe",
    "TradingSession",
]
