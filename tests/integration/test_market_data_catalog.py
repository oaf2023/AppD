"""Pruebas de integración del symbol master (BUILD-028, REQ-025/REQ-099, K §2, Q §2.7/§2.8).

ASGI + PostgreSQL real sobre `platform_market_data`: semilla idempotente de la
migración 0002, endpoints `market-data/symbols` (público) e `instruments*`
(JWT `read`, cursor §1.4), suspensión → `halted` + evento `SymbolUpdated` en
el outbox y versionado de specs (`activate_spec_version`, REQ-025).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from market_data.catalog import (
    activate_spec_version,
    current_spec_row,
    insert_suspension,
    outbox_rows,
    row_to_spec,
    spec_rows,
)
from market_data.db import get_session_factory
from market_data.domain.models import InstrumentSpec
from market_data.domain.symbol_master import spec_asof
from market_data.seed import seed_catalog
from market_data.tables import (
    InstrumentSpecRow,
    MarketHolidayRow,
    MarketSuspensionRow,
    OutboxRow,
    SymbolRow,
    TradingSessionRow,
)
from platform_kernel.clock import utcnow
from platform_kernel.security.tokens import new_access_token
from sqlalchemy import delete

pytestmark = pytest.mark.integration

SYMBOLS = {"EUR/USD", "GBP/USD", "BTC/USD", "ETH/USD"}


async def _reset_catalog() -> None:
    """Vuelve al estado sembrado (mismos valores que la migración 0002)."""
    factory = get_session_factory()
    async with factory() as session:
        for table in (
            OutboxRow,
            MarketSuspensionRow,
            MarketHolidayRow,
            TradingSessionRow,
            InstrumentSpecRow,
            SymbolRow,
        ):
            await session.execute(delete(table))
        await seed_catalog(session)
        await session.commit()


@pytest.fixture
async def _catalog(market_data_app):  # type: ignore[no-untyped-def]
    await _reset_catalog()
    yield
    await _reset_catalog()


def _auth() -> dict[str, str]:
    token = new_access_token(
        user_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        roles=["user"],
        secret=os.environ["JWT_SECRET"],
        issuer="platform-identity",
        audience="platform-api",
        ttl_seconds=900,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_migracion_0002_siembra_el_catalogo(market_data_client) -> None:
    """La migración crea los 4 símbolos demo: `symbols` es público sin JWT."""
    response = await market_data_client.get("/api/v1/market-data/symbols")
    assert response.status_code == 200
    body = response.json()
    assert body["simulated"] is True
    assert body["as_of"]
    assert {item["symbol"] for item in body["data"]} == SYMBOLS
    by_symbol = {item["symbol"]: item for item in body["data"]}
    eur = by_symbol["EUR/USD"]
    assert eur["asset_class"] == "forex"
    assert eur["status"] == "active"
    assert eur["market"]["status"] in {"open", "closed"}
    assert eur["market"]["reason"] in {"session", "out_of_hours"}
    assert eur["feed"]["source"] == "MOCK"
    btc = by_symbol["BTC/USD"]
    assert btc["asset_class"] == "crypto"
    assert btc["market"]["status"] == "open"  # crypto 24/7
    assert btc["market"]["next_close"] is not None


async def test_instruments_requiere_jwt(market_data_client) -> None:
    anon = await market_data_client.get("/api/v1/instruments")
    assert anon.status_code == 401
    auth = await market_data_client.get("/api/v1/instruments", headers=_auth())
    assert auth.status_code == 200


async def test_instruments_paginacion_y_filtros(market_data_client, _catalog) -> None:
    page1 = await market_data_client.get("/api/v1/instruments", params={"limit": 2}, headers=_auth())
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["data"]) == 2
    assert body1["page"]["has_more"] is True
    cursor = body1["page"]["next_cursor"]
    assert cursor
    assert body1["data"][0]["symbol"] < body1["data"][1]["symbol"]

    page2 = await market_data_client.get("/api/v1/instruments", params={"limit": 2, "cursor": cursor}, headers=_auth())
    body2 = page2.json()
    assert len(body2["data"]) == 2
    assert body2["page"]["has_more"] is False
    first = {item["symbol"] for item in body1["data"]}
    second = {item["symbol"] for item in body2["data"]}
    assert first.isdisjoint(second)
    assert first | second == SYMBOLS

    forex = await market_data_client.get("/api/v1/instruments", params={"asset_class": "forex"}, headers=_auth())
    assert forex.status_code == 200
    items = forex.json()["data"]
    assert {item["asset_class"] for item in items} == {"forex"}
    assert len(items) == 2

    active = await market_data_client.get("/api/v1/instruments", params={"status": "active"}, headers=_auth())
    assert active.status_code == 200
    assert len(active.json()["data"]) == 4


async def test_instrument_detalle_y_404(market_data_client, _catalog) -> None:
    ok = await market_data_client.get("/api/v1/instruments/EUR/USD", headers=_auth())
    assert ok.status_code == 200
    body = ok.json()
    assert body["symbol"] == "EUR/USD"
    assert body["tick_size"] == "0.00001"
    assert body["price_precision"] == 5
    assert body["version"] == 1
    assert body["market"]["status"] in {"open", "closed"}

    missing = await market_data_client.get("/api/v1/instruments/XXX/ZZZ", headers=_auth())
    assert missing.status_code == 404
    assert missing.json()["type"] == "urn:platform:error:not-found"


async def test_instrument_specs_con_sesiones(market_data_client, _catalog) -> None:
    forex = await market_data_client.get("/api/v1/instruments/EUR/USD/specs", headers=_auth())
    assert forex.status_code == 200
    body = forex.json()
    assert body["version"] == 1
    assert body["valid_to"] is None
    assert body["tick_size"] == "0.00001"
    assert body["price_precision"] == 5
    assert len(body["sessions"]) == 5
    assert all(item["timezone"] == "Etc/UTC" for item in body["sessions"])
    assert body["fee_schedule"]["mode"] == "demo"
    assert body["market"]["status"] in {"open", "closed"}

    crypto = await market_data_client.get("/api/v1/instruments/BTC/USD/specs", headers=_auth())
    assert crypto.status_code == 200
    btc = crypto.json()
    assert len(btc["sessions"]) == 7
    assert btc["tick_size"] == "0.01"
    assert btc["price_precision"] == 2
    assert btc["market"]["status"] == "open"  # 24/7


async def test_suspension_halta_y_emite_symbol_updated(market_data_app, market_data_client, _catalog) -> None:
    factory = get_session_factory()
    now = utcnow()
    async with factory() as session:
        await insert_suspension(
            session,
            symbol="EUR/USD",
            code="manual",
            reason="mantenimiento programado",
            starts_at=now - timedelta(minutes=1),
        )
        await session.commit()

    response = await market_data_client.get("/api/v1/market-data/symbols")
    eur = next(item for item in response.json()["data"] if item["symbol"] == "EUR/USD")
    assert eur["market"]["status"] == "halted"
    assert eur["market"]["reason"] == "suspended:manual"
    gbp = next(item for item in response.json()["data"] if item["symbol"] == "GBP/USD")
    assert gbp["market"]["status"] != "halted"  # la suspensión es por símbolo

    async with factory() as session:
        events = await outbox_rows(session, event_type="SymbolUpdated")
    assert len(events) == 1
    row = events[0]
    assert row.topic == "market.symbols.changed"
    payload = row.payload
    assert payload["event_type"] == "SymbolUpdated"
    assert payload["schema_version"] == 1
    assert payload["aggregate_id"] == "EUR/USD"
    assert payload["aggregate_type"] == "Symbol"
    assert payload["producer"] == "market-data"
    assert payload["event_id"]
    assert payload["timestamp"]
    assert payload["payload"] == {"symbol": "EUR/USD", "event": "suspended", "code": "manual"}


async def test_activar_version_de_spec_no_afecta_version_anterior(
    market_data_app, market_data_client, _catalog
) -> None:
    factory = get_session_factory()
    now = utcnow()
    v2 = InstrumentSpec(
        symbol="EUR/USD",
        version=2,
        valid_from=now,
        valid_to=None,
        tick_size=Decimal("0.00002"),
        pip_size=Decimal("0.00002"),
        contract_size=Decimal("1"),
        min_volume=Decimal("0.01"),
        max_volume=Decimal("10000000"),
        volume_step=Decimal("0.01"),
        margin_requirements={"mode": "demo"},
        fee_schedule={"mode": "demo"},
        swap_configuration={"mode": "demo", "enabled": False},
    )
    async with factory() as session:
        await activate_spec_version(session, v2)
        await session.commit()
        current = await current_spec_row(session, "EUR/USD")
        assert current is not None
        assert current.version == 2
        assert current.valid_from == now
        rows = await spec_rows(session, "EUR/USD")
        assert len(rows) == 2

    specs = [row_to_spec(row) for row in rows]
    assert spec_asof(specs, datetime(2026, 10, 1, tzinfo=UTC)).version == 1  # la v1 sigue consultable
    assert spec_asof(specs, now + timedelta(seconds=1)).version == 2

    detail = await market_data_client.get("/api/v1/instruments/EUR/USD", headers=_auth())
    assert detail.status_code == 200
    assert detail.json()["version"] == 2
    assert detail.json()["tick_size"] == "0.00002"

    specs_resp = await market_data_client.get("/api/v1/instruments/EUR/USD/specs", headers=_auth())
    assert specs_resp.status_code == 200
    assert specs_resp.json()["version"] == 2
    assert datetime.fromisoformat(specs_resp.json()["valid_from"]) == now


async def test_cursor_invalido_devuelve_422(market_data_client, _catalog) -> None:
    response = await market_data_client.get("/api/v1/instruments", params={"cursor": "not-a-cursor"}, headers=_auth())
    assert response.status_code == 422
    assert response.json()["type"] == "urn:platform:error:validation"
