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

PRICE_EXPONENT = Decimal("0.00000001")


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


__all__ = [
    "PRICE_EXPONENT",
    "AssetClass",
    "CanonicalDataError",
    "MarketStatus",
    "MarketStatusKind",
    "ProviderCapabilities",
    "Quote",
    "Ticker",
]
