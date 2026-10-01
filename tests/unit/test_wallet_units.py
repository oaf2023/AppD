"""Pruebas unitarias de piezas transversales del Wallet (métricas, cursor, health, main).

Sin PostgreSQL ni Redpanda: la app se compone sin lifespan para `/metrics`
y el lifespan se ejecuta con migraciones/reconciliador/consumidor desactivados
(cobertura de las costuras de `wallet.main.create_app`).
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from helpers import lifespan_client
from platform_kernel.errors import ServiceUnavailableError, ValidationError
from prometheus_client import REGISTRY, Counter
from wallet import main as wallet_main
from wallet.metrics import WALLET_TRANSFERS, _shared_metric
from wallet.pagination import decode_cursor, encode_cursor
from wallet.routes import readyz

# ------------------------------------------------------------------------- métricas


def test_metrica_wallet_reutiliza_el_colector_registrado() -> None:
    again = _shared_metric(
        Counter,
        "platform_wallet_transfers_total",
        "Transferencias internas ejecutadas",
        [],
    )
    assert again is WALLET_TRANSFERS


def test_metrica_wallet_oculta_por_el_registro_reutiliza_el_fallback(monkeypatch) -> None:
    real = REGISTRY._names_to_collectors

    class _Oculto(dict):
        def get(self, key, default=None):  # type: ignore[no-untyped-def]
            return None

    def _fabrica(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("duplicado")

    monkeypatch.setattr(REGISTRY, "_names_to_collectors", _Oculto(real))
    again = _shared_metric(
        _fabrica,
        "platform_wallet_transfers_total",
        "Transferencias internas ejecutadas",
        [],
    )
    assert again is WALLET_TRANSFERS


# ------------------------------------------------------------------------ paginación


def test_decode_cursor_basura_es_error_de_validacion() -> None:
    with pytest.raises(ValidationError, match="cursor inválido"):
        decode_cursor("no-es-un-cursor")


def test_roundtrip_del_cursor_decode_devuelve_la_clave_original() -> None:
    from datetime import UTC, datetime

    ts = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    row_id = uuid.uuid4()
    assert decode_cursor(encode_cursor(ts, row_id)) == (ts, row_id)


# --------------------------------------------------------------------- health/ready


async def test_readyz_responde_no_disponible_si_falla_la_base() -> None:
    class _SesionRota:
        async def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("sin conexión")

    with pytest.raises(ServiceUnavailableError, match="base de datos no disponible"):
        await readyz(_SesionRota())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- main


async def test_metrics_endpoint_responde_sin_lifespan() -> None:
    transport = httpx.ASGITransport(app=wallet_main.app)
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
    wallet_main.run()
    args = captura["args"]
    assert args[0] == "wallet.main:app"


async def test_lifespan_sin_migracion_reconciliador_ni_consumidor(monkeypatch) -> None:
    from wallet.config import get_wallet_settings

    settings = get_wallet_settings().model_copy(
        update={"reconcile_interval_seconds": 0, "event_consumer_enabled": False}
    )
    monkeypatch.setattr(wallet_main, "get_wallet_settings", lambda: settings)
    app = wallet_main.create_app(auto_migrate=False)
    async with lifespan_client(app):
        pass
