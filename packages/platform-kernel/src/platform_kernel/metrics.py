"""metrics — métricas Prometheus + middleware de latencia/errores."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "platform_http_requests_total",
    "Solicitudes HTTP",
    ["service", "method", "route", "status"],
    registry=None,
)
REQUEST_LATENCY = Histogram(
    "platform_http_request_duration_seconds",
    "Latencia HTTP",
    ["service", "method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=None,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service: str) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._service = service

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        route = request.url.path
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            REQUEST_COUNT.labels(self._service, request.method, route, str(status)).inc()
            REQUEST_LATENCY.labels(self._service, request.method, route).observe(elapsed)


def metrics_response(registry: CollectorRegistry | None = None) -> Response:
    data = generate_latest() if registry is None else generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


__all__ = ["REQUEST_COUNT", "REQUEST_LATENCY", "MetricsMiddleware", "metrics_response"]
