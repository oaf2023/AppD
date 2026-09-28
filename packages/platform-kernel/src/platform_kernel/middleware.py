"""middleware — contexto de trazabilidad por solicitud (request_id/correlation_id)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from platform_kernel.context import bind_context

logger = logging.getLogger("platform.http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Asigna X-Request-Id / X-Correlation-Id, los vincula al contexto y responde con ellos."""

    def __init__(self, app, *, trust_client_request_id: bool = False) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._trust_client_request_id = trust_client_request_id

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        inbound_request = request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
        request_id = inbound_request if (self._trust_client_request_id and inbound_request) else str(uuid.uuid4())
        correlation_id = request.headers.get("x-correlation-id") or request_id
        with bind_context(request_id=request_id, correlation_id=correlation_id):
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            response.headers["X-Correlation-Id"] = correlation_id
            return response


__all__ = ["RequestContextMiddleware"]
