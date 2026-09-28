"""telemetry — exportación OTel de traces a un collector cuando está configurado (ADR-0013, REQ-057).

Sin `OTEL_ENDPOINT` no se instrumenta nada (cero overhead, tests sin collector).
Con endpoint: TracerProvider + exportador OTLP/HTTP, instrumentación FastAPI por app e
httpx global (propagación `traceparent` gateway → servicios), propagador W3C activo.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("platform.telemetry")

_state: dict[str, Any] = {"initialized": False, "endpoint": None}


def init_telemetry(endpoint: str | None, *, service_name: str, service_version: str = "0.1.0") -> bool:
    """Activa el exportador OTLP/HTTP y la instrumentación httpx. Idempotente."""
    if _state["initialized"]:
        return True
    if not endpoint:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

        url = endpoint.rstrip("/")
        if not url.endswith("/v1/traces"):
            url += "/v1/traces"
        resource = Resource.create({"service.name": service_name, "service.version": service_version})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=url)))
        trace.set_tracer_provider(provider)
        set_global_textmap(TraceContextTextMapPropagator())
        HTTPXClientInstrumentor().instrument()
        _state["initialized"] = True
        _state["endpoint"] = endpoint
        logger.info("telemetría OTel activa", extra={"extra_fields": {"endpoint": endpoint}})
        return True
    except Exception:
        logger.exception("no se pudo inicializar la telemetría OTel; el servicio sigue sin trazas")
        return False


def instrument_app(app: Any) -> None:
    """Instrumenta la app FastAPI (spans de entrada) si la telemetría está activa."""
    if not _state["initialized"]:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception:
        logger.exception("no se pudo instrumentar la app FastAPI")


def is_enabled() -> bool:
    return bool(_state["initialized"])


def trace_fields() -> dict[str, str]:
    """trace_id/span_id del span activo para enriquecer los logs JSON (0 si no hay span)."""
    if not _state["initialized"]:
        return {}
    try:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if ctx.trace_id:
            return {"trace_id": format(ctx.trace_id, "032x"), "span_id": format(ctx.span_id, "016x")}
    except Exception:
        return {}
    return {}


__all__ = ["init_telemetry", "instrument_app", "is_enabled", "trace_fields"]
