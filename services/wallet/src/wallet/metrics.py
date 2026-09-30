"""metrics - métricas Prometheus del Wallet Service.

Los contadores `platform_outbox_*`/compartidos se reutilizan si otro módulo ya
los registró en el mismo proceso (`prometheus_client` lanza `DuplicateTimeseries`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prometheus_client import REGISTRY, Counter


def _shared_metric(factory: Callable[..., Any], name: str, documentation: str, labelnames: list[str]) -> Any:
    """Devuelve el colector registrado para `name` o lo registra una sola vez."""
    collector = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
    if collector is not None:
        return collector
    try:
        return factory(name, documentation, labelnames)
    except ValueError:
        return REGISTRY._names_to_collectors[name]


WALLET_TRANSFERS: Counter = _shared_metric(
    Counter,
    "platform_wallet_transfers_total",
    "Transferencias internas ejecutadas",
    [],
)

WALLET_RECONCILE_MISMATCHES: Counter = _shared_metric(
    Counter,
    "platform_wallet_reconcile_mismatches_total",
    "Descuadres wallet-ledger detectados por el reconciliador (BUILD-019)",
    [],
)

__all__ = ["WALLET_RECONCILE_MISMATCHES", "WALLET_TRANSFERS", "_shared_metric"]
