"""Pruebas unitarias de normalización y tipos canónicos (BUILD-027, K §2/§4.4, REQ-028).

Sin red y sin base de datos: solo dominio (`domain/models.py`) y
`normalization.py`. Los invariantes OHLC de las velas persistidas se verifican
en `tests/integration/test_market_data_persistence.py` contra CHECKs reales.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from market_data.domain.models import Candle, CanonicalDataError, Quote, Tick
from market_data.ingest import raw_tick_from_quote
from market_data.normalization import RawTick, normalize_tick

NOW = datetime(2026, 10, 1, 12, 0, 30, tzinfo=UTC)


def _raw(**overrides: object) -> RawTick:
    base: dict[str, object] = {
        "symbol": "EUR/USD",
        "price": "1.10000000",
        "side": "na",
        "size": None,
        "ts": NOW - timedelta(seconds=5),
        "source": "MOCK",
        "simulated": True,
        "recv_ts": NOW,
    }
    base.update(overrides)
    return RawTick(**base)  # type: ignore[arg-type]


def test_normalize_accepts_decimal_str_and_int_prices() -> None:
    for price, expected in ((Decimal("1.1"), Decimal("1.1")), ("1.1", Decimal("1.1")), (1, Decimal("1"))):
        tick = normalize_tick(_raw(price=price), now=NOW)
        assert tick.price == expected
        assert tick.symbol == "EUR/USD"
        assert tick.side == "na"
        assert tick.size is None


def test_normalize_rejects_float_and_bool() -> None:
    for price in (1.1, True):
        with pytest.raises(CanonicalDataError):
            normalize_tick(_raw(price=price), now=NOW)


def test_normalize_rejects_invalid_symbol_side_and_prices() -> None:
    for overrides in (
        {"symbol": "eur/usd"},
        {"symbol": "X"},
        {"symbol": ""},
        {"side": "up"},
        {"price": "0"},
        {"price": "-1.1"},
        {"size": "-1"},
        {"source": ""},
        {"price": "abc"},
        {"price": object()},
    ):
        with pytest.raises(CanonicalDataError):
            normalize_tick(_raw(**overrides), now=NOW)


def test_normalize_rejects_future_and_naive_timestamps() -> None:
    with pytest.raises(CanonicalDataError):
        normalize_tick(_raw(ts=NOW + timedelta(seconds=10)), now=NOW)
    with pytest.raises(CanonicalDataError):
        normalize_tick(_raw(ts=datetime(2026, 10, 1, 12, 0, 25)), now=NOW)
    with pytest.raises(CanonicalDataError):
        normalize_tick(_raw(recv_ts=datetime(2026, 10, 1, 12, 0, 25)), now=NOW)


def test_normalize_keeps_provider_seq_and_recv_defaults() -> None:
    tick = normalize_tick(_raw(provider_seq=7, recv_ts=None), now=NOW)
    assert tick.provider_seq == 7
    assert tick.recv_ts == NOW


def test_tick_invariants() -> None:
    with pytest.raises(CanonicalDataError):
        Tick(
            symbol="EUR/USD",
            price=Decimal("1.1"),
            side="buy",
            size=Decimal("-1"),
            ts=NOW,
            recv_ts=NOW,
            source="MOCK",
            simulated=True,
        )
    with pytest.raises(CanonicalDataError):
        Tick(
            symbol="EUR/USD",
            price=Decimal("0"),
            side="na",
            size=None,
            ts=NOW,
            recv_ts=NOW,
            source="MOCK",
            simulated=True,
        )
    with pytest.raises(CanonicalDataError):
        Tick(
            symbol="EUR/USD",
            price=Decimal("1.1"),
            side="na",
            size=None,
            ts=NOW,
            recv_ts=NOW,
            source="MOCK",
            simulated=True,
            provider_seq=-1,
        )


def _candle(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "symbol": "EUR/USD",
        "timeframe": "1m",
        "ts": datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        "open": Decimal("1.1000"),
        "high": Decimal("1.1010"),
        "low": Decimal("1.0995"),
        "close": Decimal("1.1005"),
        "volume": None,
        "gap": False,
        "source": "MOCK",
        "simulated": True,
    }
    base.update(overrides)
    return base


def test_candle_valid_ohlc_and_gap_forms() -> None:
    candle = Candle(**_candle())  # type: ignore[arg-type]
    assert candle.low <= min(candle.open, candle.close)  # type: ignore[arg-type]
    assert candle.high >= max(candle.open, candle.close)  # type: ignore[arg-type]

    gap = Candle(**_candle(gap=True, open=None, high=None, low=None, close=None, volume=None))  # type: ignore[arg-type]
    assert gap.gap is True
    assert gap.close is None


def test_candle_rejects_violated_invariants() -> None:
    with pytest.raises(CanonicalDataError):
        Candle(**_candle(low=Decimal("1.1005")))  # low > min(open, close)
    with pytest.raises(CanonicalDataError):
        Candle(**_candle(high=Decimal("1.0999")))  # high < max(open, close)
    with pytest.raises(CanonicalDataError):
        Candle(**_candle(volume=Decimal("-1")))
    with pytest.raises(CanonicalDataError):
        Candle(**_candle(gap=True, close=Decimal("1.1005")))  # gap nunca fabricado
    with pytest.raises(CanonicalDataError):
        Candle(**_candle(close=None))  # gap=false exige OHLC completo
    with pytest.raises(CanonicalDataError):
        Candle(**_candle(timeframe="2m"))  # type: ignore[arg-type]


def test_raw_tick_from_quote_derives_canonical_neutral_tick() -> None:
    quote = Quote(
        symbol="BTC/USD",
        bid=Decimal("83548.0"),
        ask=Decimal("83549.0"),
        last=Decimal("83548.5"),
        ts=NOW - timedelta(seconds=1),
        source="MOCK",
        simulated=True,
    )
    raw = raw_tick_from_quote(quote, recv_ts=NOW)
    tick = normalize_tick(raw, now=NOW)
    assert tick.price == Decimal("83548.5")
    assert tick.side == "na"
    assert tick.size is None
    assert tick.provider_seq is None
    assert tick.simulated is True
