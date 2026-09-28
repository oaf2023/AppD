"""telemetry — comportamiento sin collector y enriquecimiento de logs con trace_id."""

from __future__ import annotations

import json
import logging

from platform_kernel import telemetry
from platform_kernel.logging import JsonFormatter


def test_sin_endpoint_no_inicializa() -> None:
    assert telemetry.init_telemetry(None, service_name="identity") is False
    assert telemetry.init_telemetry("", service_name="identity") is False
    assert telemetry.is_enabled() is False
    assert telemetry.trace_fields() == {}


def test_instrument_app_es_noop_sin_telemetria() -> None:
    from fastapi import FastAPI

    app = FastAPI()
    telemetry.instrument_app(app)  # no debe fallar ni instrumentar
    assert app.user_middleware == []


def test_logs_sin_trace_id_por_defecto() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hola", None, None)
    payload = json.loads(JsonFormatter("identity").format(record))
    assert "trace_id" not in payload


def test_trace_fields_con_span_activo() -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    previous_enabled = telemetry._state["initialized"]
    telemetry._state["initialized"] = True
    try:
        trace.set_tracer_provider(TracerProvider())
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("prueba"):
            fields = telemetry.trace_fields()
        assert len(fields["trace_id"]) == 32
        assert len(fields["span_id"]) == 16
        int(fields["trace_id"], 16)
    finally:
        telemetry._state["initialized"] = previous_enabled
