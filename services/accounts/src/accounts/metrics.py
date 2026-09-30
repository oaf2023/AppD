"""metrics — métricas Prometheus compartidas del Accounts Service.

Los contadores `platform_outbox_*` son por servicio (etiqueta `service`) y ya
están registrados por `identity.outbox` cuando la suite importa varios módulos
en el mismo proceso (`prometheus_client` lanza `DuplicateTimeseries` al
registrarlos dos veces). `_shared_metric` reutiliza el colector existente.
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


ACCOUNTS_CREATED: Counter = _shared_metric(
    Counter,
    "platform_accounts_created_total",
    "Cuentas de trading creadas",
    ["type"],
)

__all__ = ["ACCOUNTS_CREATED", "_shared_metric"]
