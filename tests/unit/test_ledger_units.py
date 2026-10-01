"""Pruebas unitarias de piezas transversales del Ledger (cursor y main).

Sin PostgreSQL ni Redpanda: la app se compone sin lifespan para `/metrics`
y el lifespan se ejecuta con migraciones/relay/retención/consumidor
desactivados (cobertura de las costuras de `ledger.main.create_app`).
"""

from __future__ import annotations

import httpx
import pytest
from helpers import lifespan_client
from ledger import main as ledger_main
from ledger.pagination import decode_cursor, encode_cursor
from platform_kernel.errors import ValidationError

# ------------------------------------------------------------------------ paginación


def test_decode_cursor_basura_es_error_de_validacion() -> None:
    with pytest.raises(ValidationError, match="cursor inválido"):
        decode_cursor("no-es-un-cursor")


def test_roundtrip_del_cursor_decode_devuelve_la_clave_original() -> None:
    import uuid
    from datetime import UTC, datetime

    ts = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    row_id = uuid.uuid4()
    assert decode_cursor(encode_cursor(ts, row_id)) == (ts, row_id)


# --------------------------------------------------------------------------- main


async def test_metrics_endpoint_responde_sin_lifespan() -> None:
    transport = httpx.ASGITransport(app=ledger_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    assert "# HELP" in response.text


def test_run_invoca_uvicorn_con_el_nombre_de_la_app(monkeypatch) -> None:
    import uvicorn

    captura: dict[str, object] = {}

    def _fake(*args, **kwargs):  # type: ignore[no-untyped-def]
        captura["args"] = args
        captura["kwargs"] = kwargs

    monkeypatch.setattr(uvicorn, "run", _fake)
    ledger_main.run()
    args = captura["args"]
    assert args[0] == "ledger.main:app"


async def test_lifespan_sin_migracion_relay_retencion_ni_consumidor(monkeypatch) -> None:
    from ledger.config import get_ledger_settings

    settings = get_ledger_settings().model_copy(
        update={
            "outbox_relay_enabled": False,
            "retention_sweep_enabled": False,
            "event_consumer_enabled": False,
        }
    )
    monkeypatch.setattr(ledger_main, "get_ledger_settings", lambda: settings)
    app = ledger_main.create_app(auto_migrate=False)
    async with lifespan_client(app):
        pass
