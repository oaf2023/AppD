"""Tests de contrato del MarketDataProvider canónico y su mock (BUILD-026, K §1.1/§1.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from inspect import signature

import pytest
from market_data.config import MarketDataSettings
from market_data.domain.models import CanonicalDataError, MarketStatus, ProviderCapabilities, Quote, Ticker
from market_data.domain.protocols import MarketDataProvider, ProviderError, UnknownSymbolError
from market_data.providers import DEFAULT_UNIVERSE, MockMarketDataProvider, create_market_data_provider
from market_data.providers.mock import PROVIDER_ID, SOURCE

_FIXED_TS = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _mock(seed: int = 42) -> MockMarketDataProvider:
    return MockMarketDataProvider(seed=seed, clock=lambda: _FIXED_TS)


def _provider(seed: int = 42) -> MarketDataProvider:
    provider: MarketDataProvider = _mock(seed)
    return provider


async def test_mismo_seed_misma_serie_bit_a_bit() -> None:
    a, b = _mock(), _mock()
    for symbol in DEFAULT_UNIVERSE:
        for _ in range(8):
            quote_a = await a.get_quote(symbol)
            quote_b = await b.get_quote(symbol)
            assert (quote_a.bid, quote_a.ask, quote_a.last) == (quote_b.bid, quote_b.ask, quote_b.last)


async def test_seed_distinta_serie_distinta() -> None:
    a, b = _mock(42), _mock(43)
    distintas = 0
    for _ in range(10):
        if (await a.get_quote("EUR/USD")).last != (await b.get_quote("EUR/USD")).last:
            distintas += 1
    assert distintas > 0


async def test_etiqueta_req_024_en_todo() -> None:
    mock = _mock()
    for symbol in DEFAULT_UNIVERSE:
        quote = await mock.get_quote(symbol)
        assert quote.simulated is True
        assert quote.source == SOURCE == "MOCK"
    for ticker in await mock.get_tickers():
        assert ticker.quote.simulated is True
        assert ticker.quote.source == SOURCE
    status = await mock.get_market_status()
    assert status.simulated is True
    assert status.source == SOURCE
    assert mock.capabilities().simulated is True


async def test_precios_decimal_nunca_float() -> None:
    quote = await _mock().get_quote("EUR/USD")
    for value in (quote.bid, quote.ask, quote.last):
        assert isinstance(value, Decimal)
        assert not isinstance(value, float)
        assert value > 0
    assert quote.last.as_tuple().exponent == -8


def test_float_rechazado_en_construccion() -> None:
    with pytest.raises(CanonicalDataError, match="Decimal"):
        Quote(
            symbol="EUR/USD",
            bid=0.99,  # type: ignore[arg-type]
            ask=Decimal("1.01"),
            last=Decimal("1.00"),
            ts=_FIXED_TS,
            source=SOURCE,
            simulated=True,
        )


async def test_invariante_bid_ask_y_spread() -> None:
    mock = _mock()
    for symbol in DEFAULT_UNIVERSE:
        for _ in range(6):
            quote = await mock.get_quote(symbol)
            assert quote.bid <= quote.ask
            assert quote.spread == quote.ask - quote.bid
            assert quote.spread > 0


def test_quote_invertida_rechazada() -> None:
    with pytest.raises(CanonicalDataError, match="bid"):
        Quote(
            symbol="EUR/USD",
            bid=Decimal("2"),
            ask=Decimal("1"),
            last=Decimal("1.5"),
            ts=_FIXED_TS,
            source=SOURCE,
            simulated=True,
        )


async def test_simbolo_desconocido_fail_closed() -> None:
    mock = _mock()
    with pytest.raises(UnknownSymbolError):
        await mock.get_quote("NOPE/USD")
    with pytest.raises(UnknownSymbolError):
        await mock.get_tickers(["NOPE/USD"])
    with pytest.raises(UnknownSymbolError):
        await mock.get_market_status("NOPE/USD")
    with pytest.raises(ProviderError):
        await mock.get_quote("NOPE/USD")


async def test_tickers_universo_subset_y_sin_estimacion_24h() -> None:
    mock = _mock()
    todos = await mock.get_tickers()
    assert [ticker.quote.symbol for ticker in todos] == sorted(DEFAULT_UNIVERSE)
    subset = await mock.get_tickers(["BTC/USD", "EUR/USD"])
    assert [ticker.quote.symbol for ticker in subset] == ["BTC/USD", "EUR/USD"]
    assert await mock.get_tickers([]) == []
    for ticker in todos:
        assert ticker.volume_24h is None
        assert ticker.change_pct is None
        assert ticker.high_24h is None
        assert ticker.low_24h is None


async def test_status_global_simulacion_24x7() -> None:
    status = await _mock().get_market_status(None)
    assert status.symbol is None
    assert status.status == "open"
    assert status.next_open is None
    assert status.next_close is None
    assert status.as_of == _FIXED_TS
    assert status.simulated is True


async def test_capabilities_del_mock() -> None:
    caps = _mock().capabilities()
    assert caps.provider_id == PROVIDER_ID == "mock"
    assert caps.granularity == "tick"
    assert caps.supports_rest is False
    assert caps.supports_ws is False
    assert caps.rate_limit is None
    assert set(caps.asset_classes) == {"forex", "crypto"}


def test_firmas_sin_cliente_http() -> None:
    for name in ("get_quote", "get_tickers", "get_market_status", "capabilities"):
        params = signature(getattr(MockMarketDataProvider, name)).parameters
        assert "client" not in params


def test_factory_devuelve_mock_configurado() -> None:
    settings = MarketDataSettings(environment="test")
    provider = create_market_data_provider(settings)
    assert provider.capabilities().provider_id == "mock"


def test_factory_driver_desconocido_rechazado() -> None:
    settings = MarketDataSettings.model_construct(environment="test", provider_driver="real")
    with pytest.raises(ValueError, match="desconocido"):
        create_market_data_provider(settings)


async def test_serie_golden_seed_42() -> None:
    mock = _mock(seed=42)
    lasts = [(await mock.get_quote("EUR/USD")).last for _ in range(5)]
    assert lasts == [
        Decimal("1.00310000"),
        Decimal("1.00440403"),
        Decimal("1.00751768"),
        Decimal("1.01074174"),
        Decimal("1.01134819"),
    ]
    primero = await _mock(seed=42).get_quote("EUR/USD")
    assert (primero.bid, primero.ask, primero.last) == (
        Decimal("1.00259845"),
        Decimal("1.00360155"),
        Decimal("1.00310000"),
    )


async def test_ts_usa_reloj_inyectado_sin_tiempo_real_en_precios() -> None:
    mock = _mock()
    quote = await mock.get_quote("EUR/USD")
    assert quote.ts == _FIXED_TS
    assert quote.ts.tzinfo is not None


def test_universo_vacio_rechazado() -> None:
    with pytest.raises(CanonicalDataError, match="universo"):
        MockMarketDataProvider(symbols={})


def test_mock_es_sustituible_como_protocol() -> None:
    provider = _provider()
    assert provider.capabilities().provider_id == "mock"


def _quote(**overrides: object) -> Quote:
    kwargs: dict[str, object] = {
        "symbol": "EUR/USD",
        "bid": Decimal("1"),
        "ask": Decimal("2"),
        "last": Decimal("1.5"),
        "ts": _FIXED_TS,
        "source": SOURCE,
        "simulated": True,
    }
    kwargs.update(overrides)
    return Quote(**kwargs)  # type: ignore[arg-type]


def test_quote_validaciones() -> None:
    with pytest.raises(CanonicalDataError, match="symbol"):
        _quote(symbol="")
    with pytest.raises(CanonicalDataError, match="source"):
        _quote(source="")
    with pytest.raises(CanonicalDataError, match="> 0"):
        _quote(bid=Decimal("0"))
    with pytest.raises(CanonicalDataError, match="zona horaria"):
        _quote(ts=datetime(2026, 10, 1, 12, 0, 0))


def test_ticker_validaciones() -> None:
    base = _quote()
    with pytest.raises(CanonicalDataError, match="volume_24h"):
        Ticker(quote=base, volume_24h=1.5)  # type: ignore[arg-type]
    with pytest.raises(CanonicalDataError, match="negativo"):
        Ticker(quote=base, volume_24h=Decimal("-1"))
    with pytest.raises(CanonicalDataError, match="high_24h"):
        Ticker(quote=base, high_24h=Decimal("0"))
    with pytest.raises(CanonicalDataError, match="low_24h"):
        Ticker(quote=base, low_24h=Decimal("-2"))
    assert Ticker(quote=base, volume_24h=Decimal("10")).volume_24h == Decimal("10")


def _status(**overrides: object) -> MarketStatus:
    kwargs: dict[str, object] = {
        "symbol": None,
        "status": "open",
        "reason": "simulación continua",
        "as_of": _FIXED_TS,
        "source": SOURCE,
        "simulated": True,
    }
    kwargs.update(overrides)
    return MarketStatus(**kwargs)  # type: ignore[arg-type]


def test_market_status_validaciones() -> None:
    with pytest.raises(CanonicalDataError, match="valor desconocido"):
        _status(status="sideways")
    with pytest.raises(CanonicalDataError, match="reason"):
        _status(reason="")
    with pytest.raises(CanonicalDataError, match="source"):
        _status(source="")
    with pytest.raises(CanonicalDataError, match="zona horaria"):
        _status(as_of=datetime(2026, 10, 1, 12, 0, 0))
    with pytest.raises(CanonicalDataError, match="next_open"):
        _status(next_open=datetime(2026, 10, 2, 9, 0, 0))
    with pytest.raises(CanonicalDataError, match="next_close"):
        _status(next_close=datetime(2026, 10, 2, 17, 0, 0))
    assert _status(status="halted").status == "halted"


def test_capabilities_validaciones() -> None:
    base = dict(
        provider_id="mock",
        asset_classes=("forex",),
        granularity="tick",
        supports_rest=False,
        supports_ws=False,
        simulated=True,
    )
    assert ProviderCapabilities(**base).provider_id == "mock"  # type: ignore[arg-type]
    with pytest.raises(CanonicalDataError, match="provider_id"):
        ProviderCapabilities(**{**base, "provider_id": ""})  # type: ignore[arg-type]
    with pytest.raises(CanonicalDataError, match="asset_classes"):
        ProviderCapabilities(**{**base, "asset_classes": ()})  # type: ignore[arg-type]
    with pytest.raises(CanonicalDataError, match="granularity"):
        ProviderCapabilities(**{**base, "granularity": ""})  # type: ignore[arg-type]
