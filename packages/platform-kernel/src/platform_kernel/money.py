"""money — manejo de dinero sin floats.

Regla ADR-0006: el dinero nunca usa float. Se usa Decimal con precisión fija
(NUMERIC(38,18) en PostgreSQL) y, cuando la moneda tiene unidad mínima conocida,
se admite representación en unidades enteras (amount_minor).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TWO = Decimal("0.01")
ZERO = Decimal("0")

MINOR_UNITS: dict[str, int] = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "JPY": 0,
    "USDT": 6,
    "BTC": 8,
}


class MoneyError(ValueError):
    """Error de representación o aritmética monetaria."""


def to_decimal(value: str | int | Decimal) -> Decimal:
    """Convierte a Decimal rechazando float explícitamente (prohibido ADR-0006)."""
    if isinstance(value, float):
        raise MoneyError("float prohibido para dinero; usa str, int o Decimal")
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise MoneyError(f"valor monetario inválido: {value!r}") from exc
    return result


def quantize(value: str | int | Decimal, currency: str, decimals: int | None = None) -> Decimal:
    """Redondeo monetario ROUND_HALF_UP a la precisión de la moneda."""
    places = decimals if decimals is not None else MINOR_UNITS.get(currency, 8)
    exp = Decimal(1).scaleb(-places)
    return to_decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def to_minor_units(value: str | int | Decimal, currency: str) -> int:
    """Convierte a unidades enteras mínimas (para monedas con decimales fijos)."""
    if currency not in MINOR_UNITS:
        raise MoneyError(f"unidad mínima desconocida para {currency}")
    places = MINOR_UNITS[currency]
    quantized = to_decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return int(quantized * (10**places))


def from_minor_units(minor: int, currency: str) -> Decimal:
    if currency not in MINOR_UNITS:
        raise MoneyError(f"unidad mínima desconocida para {currency}")
    places = MINOR_UNITS[currency]
    return Decimal(minor).scaleb(-places)


def sum_decimal(values: list[str | int | Decimal]) -> Decimal:
    total = ZERO
    for v in values:
        total += to_decimal(v)
    return total


__all__ = [
    "MINOR_UNITS",
    "TWO",
    "ZERO",
    "MoneyError",
    "from_minor_units",
    "quantize",
    "sum_decimal",
    "to_decimal",
    "to_minor_units",
]
