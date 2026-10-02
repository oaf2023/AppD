"""metrics — métricas Prometheus compartidas del Market Data Service (R §7.2).

Los contadores `platform_outbox_*` son por servicio (etiqueta `service`) y ya
pueden estar registrados por `identity.outbox`/`accounts.outbox` cuando la
suite importa varios módulos en el mismo proceso (`prometheus_client` lanza
`DuplicateTimeseries`). `_shared_metric` reutiliza el colector existente
(mismo patrón que `accounts.metrics`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from prometheus_client import REGISTRY, Counter, Gauge


def _shared_metric(factory: Callable[..., Any], name: str, documentation: str, labelnames: list[str]) -> Any:
    """Devuelve el colector registrado para `name` o lo registra una sola vez."""
    collector = getattr(REGISTRY, "_names_to_collectors", {}).get(name)
    if collector is not None:
        return collector
    try:
        return factory(name, documentation, labelnames)
    except ValueError:
        return REGISTRY._names_to_collectors[name]


# --- outbox (BUILD-029; compartidos con identity/accounts) -------------------
BACKLOG_GAUGE: Gauge = _shared_metric(
    Gauge,
    "platform_outbox_backlog",
    "Eventos del outbox pendientes de publicar o enviar a la DLQ",
    ["service"],
)
PUBLISHED_COUNTER: Counter = _shared_metric(
    Counter,
    "platform_outbox_published_total",
    "Eventos del outbox publicados en Redpanda",
    ["service"],
)
DEAD_LETTERED_COUNTER: Counter = _shared_metric(
    Counter,
    "platform_outbox_dead_lettered_total",
    "Eventos del outbox enviados a la DLQ",
    ["service"],
)

# --- hub WebSocket (R §7.2, BUILD-029) --------------------------------------
HUB_NAME = "market-data"
WS_CONNECTIONS_ACTIVE: Gauge = _shared_metric(
    Gauge,
    "ws_connections_active",
    "Conexiones WebSocket activas en el hub",
    ["hub", "mode"],
)
WS_CONNECTIONS_TOTAL: Counter = _shared_metric(
    Counter,
    "ws_connections_total",
    "Handshakes WebSocket aceptados o rechazados",
    ["hub", "result"],
)
WS_MESSAGES_SENT: Counter = _shared_metric(
    Counter,
    "ws_messages_sent_total",
    "Frames WebSocket enviados al cliente",
    ["hub", "topic", "type"],
)
WS_MESSAGES_RECV: Counter = _shared_metric(
    Counter,
    "ws_messages_recv_total",
    "Frames WebSocket recibidos del cliente",
    ["hub", "type"],
)
WS_SUBSCRIPTIONS_ACTIVE: Gauge = _shared_metric(
    Gauge,
    "ws_subscriptions_active",
    "Suscripciones activas por patrón de topic",
    ["hub", "topic_pattern"],
)
WS_DISCONNECTS: Counter = _shared_metric(
    Counter,
    "ws_disconnects_total",
    "Desconexiones WebSocket por motivo",
    ["hub", "reason"],
)
WS_BACKPRESSURE_ADVISORIES: Counter = _shared_metric(
    Counter,
    "ws_backpressure_advisories_total",
    "Advisories de slow_consumer enviados",
    ["hub"],
)
WS_BACKPRESSURE_DISCONNECTS: Counter = _shared_metric(
    Counter,
    "ws_backpressure_disconnects_total",
    "Desconexiones por cola llena (objetivo ≈ 0, R §5.2)",
    ["hub"],
)
WS_HEARTBEAT_TIMEOUTS: Counter = _shared_metric(
    Counter,
    "ws_heartbeat_timeouts_total",
    "Cierres por timeout de heartbeat (2 pings sin pong)",
    ["hub"],
)
WS_AUTH_FAILURES: Counter = _shared_metric(
    Counter,
    "ws_auth_failures_total",
    "Fallos de autenticación del handshake WS",
    ["hub", "cause"],
)
WS_SUBSCRIBE_DENIED: Counter = _shared_metric(
    Counter,
    "ws_subscribe_denied_total",
    "Suscripciones rechazadas (anti-BOLA, catálogo)",
    ["hub", "cause"],
)
WS_RESYNC_REQUESTS: Counter = _shared_metric(
    Counter,
    "ws_resync_requests_total",
    "Peticiones `resync` y su resultado",
    ["hub", "cause"],
)

__all__ = [
    "BACKLOG_GAUGE",
    "DEAD_LETTERED_COUNTER",
    "HUB_NAME",
    "PUBLISHED_COUNTER",
    "WS_AUTH_FAILURES",
    "WS_BACKPRESSURE_ADVISORIES",
    "WS_BACKPRESSURE_DISCONNECTS",
    "WS_CONNECTIONS_ACTIVE",
    "WS_CONNECTIONS_TOTAL",
    "WS_DISCONNECTS",
    "WS_HEARTBEAT_TIMEOUTS",
    "WS_MESSAGES_RECV",
    "WS_MESSAGES_SENT",
    "WS_RESYNC_REQUESTS",
    "WS_SUBSCRIBE_DENIED",
    "WS_SUBSCRIPTIONS_ACTIVE",
    "_shared_metric",
]
