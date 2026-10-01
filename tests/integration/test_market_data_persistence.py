"""Pruebas de integración del pipeline ticks/velas (BUILD-027, K §2/§4.4, REQ-028).

ASGI + PostgreSQL real sobre `platform_market_data`: normalización →
deduplicación → agregación 1m con invariantes H/L (REQ-028) → huecos
explícitos `gap=true` (K §4.4(c), nunca fabricados) → REST de Q §2.7 con
JWT (`read`) y cursor §1.4. El poller queda apagado; el ingest se dispara a
mano con reloj controlado.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from market_data.db import get_session_factory
from market_data.domain.models import Quote
from market_data.ingest import IngestPoller, IngestService, IngestStats
from market_data.normalization import RawTick
from market_data.store import bucket_start_1m, list_candle_rows, list_tick_rows
from market_data.tables import CandleRow, TickRow
from platform_kernel.clock import utcnow
from platform_kernel.security.tokens import new_access_token
from sqlalchemy import delete, func, select

pytestmark = pytest.mark.integration

SYMBOL = "EUR/USD"


@pytest.fixture(autouse=True)
async def _wipe_market_data(market_data_app):  # type: ignore[no-untyped-def]
    """Vacia `market_data` antes de cada test: los tests no comparten estado."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(delete(TickRow))
        await session.execute(delete(CandleRow))
        await session.commit()


def _token() -> str:
    return new_access_token(
        user_id=str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        roles=["user"],
        secret=os.environ["JWT_SECRET"],
        issuer="platform-identity",
        audience="platform-api",
        ttl_seconds=900,
    )


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def _base() -> datetime:
    """Bucket de minuto corriente: los ticks caen dentro de la ventana por defecto."""
    return bucket_start_1m(utcnow())


def _raw(ts: datetime, price: str, *, symbol: str = SYMBOL) -> RawTick:
    return RawTick(
        symbol=symbol,
        price=price,
        side="na",
        size=None,
        ts=ts,
        source="MOCK",
        simulated=True,
        recv_ts=ts,
    )


async def _ingest_async(service: IngestService, raws: list[RawTick], now: datetime) -> IngestStats:
    return await service.ingest_raw(raws, now=now)


def _service() -> IngestService:
    from market_data.config import get_market_data_settings
    from market_data.providers.factory import create_market_data_provider

    return IngestService(get_session_factory(), create_market_data_provider(get_market_data_settings()))


async def _count(model) -> int:  # type: ignore[no-untyped-def]
    factory = get_session_factory()
    async with factory() as session:
        return int((await session.execute(select(func.count(model.id)))).scalar_one())


async def _candle(symbol: str, bucket: datetime) -> CandleRow | None:
    factory = get_session_factory()
    async with factory() as session:
        rows, _ = await list_candle_rows(
            session, symbol=symbol, timeframe="1m", from_ts=bucket, to_ts=bucket, cursor=None, limit=1
        )
        return rows[0] if rows else None


async def test_ingest_persists_ticks_and_derives_ohlc_with_invariants(market_data_app) -> None:  # type: ignore[no-untyped-def]
    base = _base()
    now = base + timedelta(seconds=30)
    raws = [
        _raw(base, "1.10000000"),
        _raw(base + timedelta(seconds=10), "1.10050000"),
        _raw(base + timedelta(seconds=20), "1.10030000"),
    ]
    stats = await _ingest_async(_service(), raws, now)

    assert stats.received == 3
    assert stats.inserted == 3
    assert stats.quarantined == 0
    assert stats.gaps_marked == 0
    assert stats.candles_updated == 1
    assert await _count(TickRow) == 3

    candle = await _candle(SYMBOL, base)
    assert candle is not None
    assert candle.gap is False
    # open = primer tick, close = último, high/low = extremos (REQ-028).
    assert candle.open == Decimal("1.10000000")
    assert candle.high == Decimal("1.10050000")
    assert candle.low == Decimal("1.10000000")
    assert candle.close == Decimal("1.10030000")
    assert candle.volume is None  # sin tamaños conocidos: jamás fabricado
    assert candle.high >= max(candle.open, candle.close)
    assert candle.low <= min(candle.open, candle.close)


async def test_quarantine_and_dedup_do_not_persist(market_data_app) -> None:  # type: ignore[no-untyped-def]
    base = _base()
    now = base + timedelta(seconds=30)
    good = _raw(base, "1.1000")
    stats = await _ingest_async(_service(), [good], now)
    assert stats.inserted == 1

    # deduplicación exacta (symbol, source, ts, price) — K §4.4 sin provider_seq
    stats = await _ingest_async(_service(), [good], now)
    assert stats.inserted == 0
    assert stats.duplicates == 1
    assert await _count(TickRow) == 1

    # cuarentena: float, precio no positivo y ts futuro nunca llegan a la BD
    stats = await _ingest_async(
        _service(),
        [
            _raw(base + timedelta(seconds=1), "1.1"),  # str OK pero duplica precio? no: ts distinto
            _raw(base + timedelta(seconds=2), 1.1),  # type: ignore[arg-type]  # float
            _raw(base + timedelta(seconds=3), "0"),
            _raw(now + timedelta(seconds=30), "1.2"),  # futuro más allá del skew
        ],
        now,
    )
    assert stats.quarantined == 3
    assert stats.inserted == 1
    assert await _count(TickRow) == 2


async def test_gaps_are_marked_explicitly_and_never_fabricated(market_data_app) -> None:  # type: ignore[no-untyped-def]
    base = _base()
    now = base + timedelta(seconds=30)
    first_bucket = base - timedelta(minutes=3)
    stats = await _ingest_async(
        _service(),
        [_raw(first_bucket, "1.0900"), _raw(base, "1.1000")],
        now,
    )
    assert stats.inserted == 2
    assert stats.gaps_marked == 2  # buckets intermedios sin ticks

    gap_1 = await _candle(SYMBOL, base - timedelta(minutes=2))
    gap_2 = await _candle(SYMBOL, base - timedelta(minutes=1))
    for gap in (gap_1, gap_2):
        assert gap is not None
        assert gap.gap is True
        assert gap.open is None and gap.high is None
        assert gap.low is None and gap.close is None  # nunca con el último precio
        assert gap.volume is None

    # llegada tardía a un bucket marcado como hueco ⇒ se recalcula con ticks reales
    late = _raw(base - timedelta(minutes=2) + timedelta(seconds=5), "1.0950")
    stats = await _ingest_async(_service(), [late], now)
    assert stats.inserted == 1
    repaired = await _candle(SYMBOL, base - timedelta(minutes=2))
    assert repaired is not None
    assert repaired.gap is False
    assert repaired.open == Decimal("1.0950")
    assert repaired.close == Decimal("1.0950")


async def test_latest_tick_requires_auth_and_returns_snapshot(market_data_app) -> None:  # type: ignore[no-untyped-def]
    import httpx

    base = _base()
    await _ingest_async(_service(), [_raw(base, "1.1010")], base + timedelta(seconds=30))
    transport = httpx.ASGITransport(app=market_data_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        anon = await client.get(f"/api/v1/market-data/ticks/{SYMBOL}")
        assert anon.status_code == 401

        ok = await client.get(f"/api/v1/market-data/ticks/{SYMBOL}", headers=_auth())
        assert ok.status_code == 200
        body = ok.json()
        assert body["symbol"] == SYMBOL
        assert body["price"] == "1.10100000"  # canónico K §2: 8 decimales
        assert body["side"] == "na"
        assert body["simulated"] is True
        assert isinstance(body["tick_id"], str)

        missing = await client.get("/api/v1/market-data/ticks/UNKNOWN", headers=_auth())
        assert missing.status_code == 404
        assert missing.json()["type"] == "urn:platform:error:not-found"


async def test_ticks_history_cursor_pagination_and_range_limit(market_data_app) -> None:  # type: ignore[no-untyped-def]
    import httpx

    base = _base()
    now = base + timedelta(seconds=30)
    raws = [
        _raw(base, "1.1000"),
        _raw(base + timedelta(seconds=1), "1.1001"),
        _raw(base + timedelta(seconds=2), "1.1002"),
    ]
    await _ingest_async(_service(), raws, now)

    transport = httpx.ASGITransport(app=market_data_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        page1 = await client.get(
            "/api/v1/market-data/ticks",
            params={"symbol": SYMBOL, "limit": 2},
            headers=_auth(),
        )
        assert page1.status_code == 200
        data = page1.json()["data"]
        page = page1.json()["page"]
        assert [row["price"] for row in data] == ["1.10020000", "1.10010000"]  # orden DESC
        assert page["has_more"] is True
        assert page["next_cursor"]

        page2 = await client.get(
            "/api/v1/market-data/ticks",
            params={"symbol": SYMBOL, "limit": 2, "cursor": page["next_cursor"]},
            headers=_auth(),
        )
        body2 = page2.json()
        assert [row["price"] for row in body2["data"]] == ["1.10000000"]
        assert body2["page"]["has_more"] is False
        assert body2["page"]["next_cursor"] is None

        # solape imposible: el siguiente cursor excluye lo ya entregado
        assert not {row["tick_id"] for row in data} & {row["tick_id"] for row in body2["data"]}

        # cursor inválido ⇒ 422 tipado (Q §1.4)
        bad = await client.get(
            "/api/v1/market-data/ticks",
            params={"symbol": SYMBOL, "cursor": "!!!no-cursor!!!"},
            headers=_auth(),
        )
        assert bad.status_code == 422
        assert bad.json()["type"] == "urn:platform:error:validation"

        # rango > 24 h rechazado (Q §5)
        wide = await client.get(
            "/api/v1/market-data/ticks",
            params={
                "symbol": SYMBOL,
                "from": (now - timedelta(hours=25)).isoformat(),
                "to": now.isoformat(),
            },
            headers=_auth(),
        )
        assert wide.status_code == 422

        # sin símbolo ⇒ validación de query
        missing = await client.get("/api/v1/market-data/ticks", headers=_auth())
        assert missing.status_code == 422

        # auth exigida también en el listado
        anon = await client.get("/api/v1/market-data/ticks", params={"symbol": SYMBOL})
        assert anon.status_code == 401


async def test_candles_endpoint_interleaves_gaps_and_validates_timeframe(market_data_app) -> None:  # type: ignore[no-untyped-def]
    import httpx

    base = _base()
    now = base + timedelta(seconds=30)
    await _ingest_async(
        _service(),
        [_raw(base - timedelta(minutes=3), "1.0900"), _raw(base, "1.1000")],
        now,
    )

    transport = httpx.ASGITransport(app=market_data_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        invalid = await client.get(f"/api/v1/market-data/candles/{SYMBOL}/2m", headers=_auth())
        assert invalid.status_code == 422  # timeframe fuera de spec ⇒ rechazo tipado

        empty_tf = await client.get(f"/api/v1/market-data/candles/{SYMBOL}/5m", headers=_auth())
        assert empty_tf.status_code == 200  # 5m se acepta; el agregador llega en BUILD-030
        assert empty_tf.json()["data"] == []
        assert empty_tf.json()["page"]["has_more"] is False

        candles = await client.get(f"/api/v1/market-data/candles/{SYMBOL}/1m", headers=_auth())
        assert candles.status_code == 200
        rows = candles.json()["data"]
        assert len(rows) == 4  # 2 reales + 2 huecos
        by_bucket = {datetime.fromisoformat(row["ts"]): row for row in rows}
        real = by_bucket[base]
        gap = by_bucket[base - timedelta(minutes=1)]
        assert real["gap"] is False
        assert real["close"] == "1.10000000"
        assert gap["gap"] is True
        assert gap["open"] is None and gap["close"] is None and gap["volume"] is None

        anon = await client.get(f"/api/v1/market-data/candles/{SYMBOL}/1m")
        assert anon.status_code == 401


async def test_status_reports_counts_latency_and_simulated(market_data_app) -> None:  # type: ignore[no-untyped-def]
    import httpx

    base = _base()
    now = base + timedelta(seconds=30)
    await _ingest_async(
        _service(),
        [_raw(base - timedelta(minutes=3), "1.0900"), _raw(base, "1.1000")],
        now,
    )

    transport = httpx.ASGITransport(app=market_data_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        anon = await client.get("/api/v1/market-data/status")
        assert anon.status_code == 401

        ok = await client.get("/api/v1/market-data/status", headers=_auth())
        assert ok.status_code == 200
        body = ok.json()
        assert body["simulated"] is True
        assert body["ingest_enabled"] is False  # poller apagado en tests
        assert body["ticks_total"] == 2
        assert body["candles_total"] == 4  # 2 reales + 2 huecos
        assert body["gaps_total"] == 2
        assert body["last_tick_ts"] is not None
        assert body["last_latency_ms"] is not None and body["last_latency_ms"] >= 0
        assert body["as_of"]


async def test_ingest_poller_runs_and_survives_provider_errors(market_data_app) -> None:  # type: ignore[no-untyped-def]
    import asyncio

    from market_data.config import get_market_data_settings
    from market_data.domain.protocols import ProviderError

    class _FailingProvider:
        provider_id = "failing"
        calls = 0

        def capabilities(self):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        async def get_tickers(self, symbols=None):  # type: ignore[no-untyped-def]
            type(self).calls += 1
            if type(self).calls == 1:
                raise ProviderError("caída simulada")
            base = _base()
            quote = Quote(
                symbol=SYMBOL,
                bid=Decimal("1.1000"),
                ask=Decimal("1.1001"),
                last=Decimal("1.10005"),
                ts=base,
                source="MOCK",
                simulated=True,
            )
            from market_data.domain.models import Ticker

            return [Ticker(quote=quote)]

    provider = _FailingProvider()
    settings = get_market_data_settings().model_copy(update={"ingest_interval_seconds": 0.05})
    poller = IngestPoller(IngestService(get_session_factory(), provider), settings)  # type: ignore[arg-type]
    await poller.start()
    try:
        deadline = utcnow() + timedelta(seconds=5)
        while (poller.last_stats is None or poller.last_stats.inserted == 0) and utcnow() < deadline:
            await asyncio.sleep(0.02)
    finally:
        await poller.stop()

    assert poller.last_stats is not None
    assert poller.last_stats.inserted == 1  # la primera pasada falló y el loop siguió
    assert provider.calls >= 2


async def test_ingest_once_from_canonical_driver(market_data_app) -> None:  # type: ignore[no-untyped-def]
    stats = await _service().ingest_once()
    assert stats.received >= 1
    assert stats.quarantined == 0
    assert stats.inserted >= 1
    assert stats.candles_updated >= 1
    assert SYMBOL in stats.symbols


async def test_independent_symbols_do_not_mix(market_data_app) -> None:  # type: ignore[no-untyped-def]
    base = _base()
    now = base + timedelta(seconds=30)
    stats = await _ingest_async(
        _service(),
        [_raw(base, "1.1000"), _raw(base, "83548.0", symbol="BTC/USD")],
        now,
    )
    assert stats.inserted == 2
    assert stats.symbols == {SYMBOL, "BTC/USD"}
    factory = get_session_factory()
    async with factory() as session:
        btc, _ = await list_tick_rows(
            session,
            symbol="BTC/USD",
            from_ts=base - timedelta(seconds=1),
            to_ts=now,
            cursor=None,
            limit=10,
        )
        assert len(btc) == 1
        assert btc[0].price == Decimal("83548.0")
