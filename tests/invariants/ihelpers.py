"""ihelpers — estrategias de hypothesis y utilidades compartidas de `tests/invariants`.

Módulo propio (no `conftest`) para que los tests puedan importarlo sin ambigüedad:
`pythonpath = ["tests"]` hace que `import conftest` resuelva al conftest raíz.
"""

from __future__ import annotations

import hypothesis.strategies as st

__all__ = ["amount_strategy", "cents"]


def amount_strategy(*, min_units: int = 1, max_units: int = 1_000_00) -> st.SearchStrategy[str]:
    """Importes en centavos como cadena decimal exacta de 2 decimales (nunca float, ADR-0006)."""
    return st.integers(min_value=min_units, max_value=max_units).map(lambda c: f"{c // 100}.{c % 100:02d}")


def cents(amount: str) -> int:
    """Centavos exactos de una cadena decimal de 2 decimales (aritmética entera en el test)."""
    whole, _, frac = amount.partition(".")
    return int(whole) * 100 + int(frac.ljust(2, "0"))
