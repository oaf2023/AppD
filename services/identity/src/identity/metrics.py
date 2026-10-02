"""metrics - métricas Prometheus compartidas de Identity (patrón accounts.metrics).

`_shared_metric` devuelve el colector ya registrado para un nombre en el
`REGISTRY` global o lo registra una sola vez. Evita `DuplicateTimeseries` cuando
varios servicios (identity, accounts, ledger, market-data) comparten nombres de
métricas globales como `platform_outbox_backlog` en el mismo proceso de tests,
sea cual sea el orden de importación.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prometheus_client import REGISTRY


def _shared_metric(factory: Callable[..., Any], name: str, documentation: str, labelnames: list[str]) -> Any:
    """Devuelve el colector registrado para `name` o lo registra una sola vez."""
    collector = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
    if collector is not None:
        return collector
    try:
        return factory(name, documentation, labelnames)
    except ValueError:
        return REGISTRY._names_to_collectors[name]


__all__ = ["_shared_metric"]
