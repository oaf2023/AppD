"""ledger — servicio de asientos contables double-entry (fuente de verdad financiera).

Implementa `docs/phase0/L-ledger-architecture.md` y ADR-0011: única vía de
escritura de saldos, append-only, idempotente y con outbox transaccional.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
