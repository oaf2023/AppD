"""values — utilidades de validación de datos numéricos de proveedores."""

from __future__ import annotations


def positive_float(value: object) -> float | None:
    """Devuelve el valor como float si es numérico (o string numérico, p. ej. Kraken) y > 0."""
    if isinstance(value, bool):
        return None
    candidate: object = value
    if isinstance(candidate, str):
        try:
            candidate = float(candidate)
        except ValueError:
            return None
    if not isinstance(candidate, int | float):
        return None
    result = float(candidate)
    return result if result > 0 else None


__all__ = ["positive_float"]
