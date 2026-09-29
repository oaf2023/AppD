"""Pruebas unitarias del Market Data Service — sin red: httpx.MockTransport."""

from __future__ import annotations

from collections import Counter

import httpx
from helpers import lifespan_client
from market_data.config import MarketDataSettings
from market_data.main import create_app

OVERVIEW = "/api/v1/market-data/overview"

FX_ROWS = [
    {"date": "2026-09-28", "base": "EUR", "quote": "GBP", "rate": 0.85785},
    {"date": "2026-09-28", "base": "EUR", "quote": "JPY", "rate": 178.5},
    {"date": "2026-09-28", "base": "EUR", "quote": "USD", "rate": 1.1378},
]

ECB_PAYLOAD = {
    "dataSets": [
        {
            "series": {
                "0:0:0:0:0": {"observations": {"0": [1.1378, 0, 0, None, None]}},
                "0:1:0:0:0": {"observations": {"0": [0.85785, 0, 0, None, None]}},
                "0:2:0:0:0": {"observations": {"0": [178.5, 0, 0, None, None]}},
            }
        }
    ],
    "structure": {
        "dimensions": {
            "series": [
                {"id": "FREQ", "values": [{"id": "D"}]},
                {"id": "CURRENCY", "values": [{"id": "USD"}, {"id": "GBP"}, {"id": "JPY"}]},
                {"id": "CURRENCY_DENOM", "values": [{"id": "EUR"}]},
                {"id": "EXR_TYPE", "values": [{"id": "SP00"}]},
                {"id": "EXR_SUFFIX", "values": [{"id": "A"}]},
            ],
            "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-09-28"}]}],
        }
    },
}

KRAKEN_PAYLOAD = {
    "error": [],
    "result": {
        "XXBTZUSD": {"c": ["83548.90000", "0.00040"]},
        "XETHZUSD": {"c": ["2685.57000", "0.02794"]},
        "USDTZUSD": {"c": ["0.99947000", "8.37028"]},
    },
}

COINGECKO_PAYLOAD = {"bitcoin": {"usd": 83579}, "ethereum": {"usd": 2686.67}, "tether": {"usd": 0.999663}}


def _settings(**overrides: object) -> MarketDataSettings:
    return MarketDataSettings(environment="test", **overrides)  # type: ignore[arg-type]


def _route_ok(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "api.frankfurter.dev":
        return httpx.Response(200, json=FX_ROWS)
    if host == "data-api.ecb.europa.eu":
        return httpx.Response(200, json=ECB_PAYLOAD)
    if host == "api.kraken.com":
        return httpx.Response(200, json=KRAKEN_PAYLOAD)
    if host == "api.coingecko.com":
        return httpx.Response(200, json=COINGECKO_PAYLOAD)
    return httpx.Response(404, text=f"host desconocido: {host}")


def _counting(handler):  # type: ignore[no-untyped-def]
    calls: Counter[str] = Counter()

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls[request.url.host] += 1
        return handler(request)

    return calls, wrapped


async def test_overview_usa_proveedores_primarios() -> None:
    calls, handler = _counting(_route_ok)
    app = create_app(transport=httpx.MockTransport(handler), settings=_settings())
    async with lifespan_client(app) as client:
        response = await client.get(OVERVIEW)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["as_of"] is not None
    classes = {c["asset_class"]: c for c in body["classes"]}

    assert classes["forex"]["status"] == "available"
    fx = {i["symbol"]: i for i in classes["forex"]["instruments"]}
    assert set(fx) == {"EUR/USD", "EUR/GBP", "EUR/JPY"}
    assert fx["EUR/USD"]["value"] == 1.1378
    assert fx["EUR/USD"]["provider"] == "frankfurter"
    assert fx["EUR/USD"]["stale"] is False
    assert fx["EUR/USD"]["simulated"] is False
    assert fx["EUR/USD"]["attribution"] == "Fuente: Banco Central Europeo (ECB)"
    assert fx["EUR/USD"]["ts"].startswith("2026-09-28")  # referencia diaria del BCE

    assert classes["crypto"]["status"] == "available"
    crypto = {i["symbol"]: i for i in classes["crypto"]["instruments"]}
    assert crypto["BTC/USD"]["value"] == 83548.9
    assert crypto["BTC/USD"]["provider"] == "kraken"
    assert crypto["USDT/USD"]["value"] == 0.99947

    # el orden de instrumentos es canónico (alfabético por símbolo)
    assert [i["symbol"] for i in classes["forex"]["instruments"]] == ["EUR/GBP", "EUR/JPY", "EUR/USD"]

    # sin llamadas a los failovers cuando los primarios responden
    assert calls["api.frankfurter.dev"] == 1
    assert calls["api.kraken.com"] == 1
    assert calls["data-api.ecb.europa.eu"] == 0
    assert calls["api.coingecko.com"] == 0


async def test_failover_a_ecb_y_coingecko() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in ("api.frankfurter.dev", "api.kraken.com"):
            return httpx.Response(500, text="boom")
        return _route_ok(request)

    app = create_app(transport=httpx.MockTransport(handler), settings=_settings())
    async with lifespan_client(app) as client:
        response = await client.get(OVERVIEW)

    assert response.status_code == 200, response.text
    classes = {c["asset_class"]: c for c in response.json()["classes"]}
    assert classes["forex"]["status"] == "available"
    assert {i["provider"] for i in classes["forex"]["instruments"]} == {"ecb"}
    fx = {i["symbol"]: i for i in classes["forex"]["instruments"]}
    assert fx["EUR/USD"]["value"] == 1.1378
    assert fx["EUR/USD"]["ts"] == "2026-09-28T00:00:00Z"  # referencia diaria del BCE

    assert classes["crypto"]["status"] == "available"
    assert {i["provider"] for i in classes["crypto"]["instruments"]} == {"coingecko"}
    crypto = {i["symbol"]: i for i in classes["crypto"]["instruments"]}
    assert crypto["BTC/USD"]["value"] == 83579
    assert crypto["BTC/USD"]["attribution"] == "Powered by CoinGecko"


async def test_cache_ttl_evita_refetch() -> None:
    calls, handler = _counting(_route_ok)
    app = create_app(
        transport=httpx.MockTransport(handler),
        settings=_settings(fx_cache_ttl_seconds=900, crypto_cache_ttl_seconds=60),
    )
    async with lifespan_client(app) as client:
        first = await client.get(OVERVIEW)
        second = await client.get(OVERVIEW)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert calls["api.frankfurter.dev"] == 1
    assert calls["api.kraken.com"] == 1


async def test_stale_sirve_ultimo_dato_bueno() -> None:
    state = {"fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down") if state["fail"] else _route_ok(request)

    app = create_app(
        transport=httpx.MockTransport(handler),
        settings=_settings(fx_cache_ttl_seconds=0, crypto_cache_ttl_seconds=0),
    )
    async with lifespan_client(app) as client:
        first = await client.get(OVERVIEW)
        first_fx_ts = {i["symbol"]: i["ts"] for i in first.json()["classes"][0]["instruments"]}
        state["fail"] = True
        second = await client.get(OVERVIEW)

    assert second.status_code == 200
    body = second.json()
    classes = {c["asset_class"]: c for c in body["classes"]}
    assert classes["forex"]["status"] == "stale"
    assert classes["crypto"]["status"] == "stale"
    fx = {i["symbol"]: i for i in classes["forex"]["instruments"]}
    assert fx["EUR/USD"]["stale"] is True
    assert fx["EUR/USD"]["value"] == 1.1378  # jamás inventado: es el snapshot previo
    assert fx["EUR/USD"]["ts"] == first_fx_ts["EUR/USD"]  # la hora es la del dato, no la de la consulta
    assert body["as_of"] is not None


async def test_unavailable_cuando_nunca_hubo_dato() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    app = create_app(
        transport=httpx.MockTransport(handler),
        settings=_settings(fx_cache_ttl_seconds=0, crypto_cache_ttl_seconds=0),
    )
    async with lifespan_client(app) as client:
        response = await client.get(OVERVIEW)

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] is None
    assert body["classes"] == [
        {"asset_class": "forex", "status": "unavailable", "instruments": []},
        {"asset_class": "crypto", "status": "unavailable", "instruments": []},
    ]


async def test_breaker_abre_tras_umbral_y_deja_de_invocar() -> None:
    calls, handler = _counting(lambda request: httpx.Response(500, text="down"))
    app = create_app(
        transport=httpx.MockTransport(handler),
        settings=_settings(fx_cache_ttl_seconds=0, crypto_cache_ttl_seconds=0),
    )
    async with lifespan_client(app) as client:
        for _ in range(5):
            assert (await client.get(OVERVIEW)).status_code == 200

    # umbral por defecto = 3: tras el tercer fallo consecutivo el proveedor queda abierto
    assert calls["api.frankfurter.dev"] == 3
    assert calls["data-api.ecb.europa.eu"] == 3
    assert calls["api.kraken.com"] == 3
    assert calls["api.coingecko.com"] == 3


async def test_healthz_y_readyz_locales() -> None:
    app = create_app(
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        settings=_settings(),
    )
    async with lifespan_client(app) as client:
        for path in ("/healthz", "/readyz"):
            response = await client.get(path)
            assert response.status_code == 200, path
            body = response.json()
            assert body == {"service": "market-data", "status": "ok", "version": "0.1.0"}


def test_gateway_expone_overview_como_ruta_publica() -> None:
    from gateway.proxy import PUBLIC_PATHS, _target_for

    assert ("GET", "/api/v1/market-data/overview") in PUBLIC_PATHS
    assert _target_for("/api/v1/market-data/overview") == "market_data"
