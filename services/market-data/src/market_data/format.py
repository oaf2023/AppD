"""format — formas canónicas de precio y parámetros (ADR-0006, K §2).

Precio: `Decimal` con 8 decimales (str, sin notación científica).
Spec: `Decimal` normalizado en notación posicional.
"""

from __future__ import annotations

from decimal import Decimal

from market_data.domain.models import PRICE_EXPONENT


def fmt_price(value: Decimal | None) -> str | None:
    """Forma canónica de precio: `Decimal` con 8 decimales (ADR-0006)."""
    if value is None:
        return None
    return str(value.quantize(PRICE_EXPONENT))


def fmt_spec(value: Decimal) -> str:
    """Forma canónica de un parámetro de spec (sin notación científica)."""
    return format(value.normalize(), "f")


__all__ = ["fmt_price", "fmt_spec"]
