"""Pruebas unitarias del hub WebSocket `/ws/v1` — sin red (BUILD-029, R §2/§3/§5).

Cubren el parsing de tópicos, la validación con stub, el ciclo
`subscribe → snapshot(seq=1) → fan-out(seq+)`, el `resync` en rango y fuera del
ring, los límites `topic_limit`/`forbidden`/`invalid_topic`, el backpressure
(4410 + advisory `slow_consumer`), las violaciones de protocolo (3 strikes ⇒
4400) y el control de ping del cliente. El `Connection` se construye con un
WebSocket de mentira: nada de esto toca el socket.
"""

from __future__ import annotations

import asyncio
from typing import cast

from market_data.config import MarketDataSettings
from market_data.ws import (
    CLOSE_BACKPRESSURE,
    CLOSE_BAD_REQUEST,
    CLOSE_GOING_AWAY,
    CLOSE_RATE_LIMITED,
    Connection,
    MarketHub,
    TopicInfo,
    is_reserved_topic,
    parse_topic,
)
from prometheus_client import REGISTRY
from starlette.websockets import WebSocket

HUB = "market-data"


def _settings(**overrides: object) -> MarketDataSettings:
    return MarketDataSettings(environment="test", **overrides)  # type: ignore[arg-type]


def _hub(**overrides: object) -> MarketHub:
    return MarketHub(_settings(**overrides))


def _conn(hub: MarketHub, *, connection_id: str = "c1") -> Connection:
    return Connection(hub, cast(WebSocket, object()), connection_id=connection_id, client_ip="127.0.0.1")


def _drain(conn: Connection) -> list[dict]:
    frames: list[dict] = []
    while True:
        try:
            frames.append(conn.queue.get_nowait())
        except asyncio.QueueEmpty:
            return frames


def _metric(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


# --------------------------------------------------------------- tópicos


def test_parse_topic_canonicos_e_invalidos() -> None:
    assert parse_topic("ticks:EUR/USD") == TopicInfo("ticks", symbol="EUR/USD")
    assert parse_topic("candles:BTC/USD:5m") == TopicInfo("candles", symbol="BTC/USD", timeframe="5m")
    assert parse_topic("system:announcements") == TopicInfo("system")
    assert parse_topic("ticks:") is None
    assert parse_topic("ticks") is None
    assert parse_topic("candles:EUR/USD:2m") is None  # timeframe fuera de TIMEFRAMES
    assert parse_topic("foo") is None


def test_reserved_topics_se_detectan() -> None:
    for prefix in ("account:1", "orders:1", "positions:1", "transactions:1", "notifications:1"):
        assert is_reserved_topic(prefix)
    assert not is_reserved_topic("ticks:EUR/USD")


def test_settings_modo_y_origenes() -> None:
    assert _settings().ws_mode == "DEMO"
    assert _settings(flag_live_trading=True).ws_mode == "LIVE"
    assert _settings().ws_allowed_origins_list == []
    assert _settings(ws_allowed_origins="https://a.example, https://b.example").ws_allowed_origins_list == [
        "https://a.example",
        "https://b.example",
    ]


async def test_validate_topic_usa_el_validador_inyectado() -> None:
    async def reject(_info: TopicInfo) -> bool:
        return False

    con_validador = MarketHub(_settings(), topic_validator=reject)
    assert await con_validador.validate_topic(TopicInfo("ticks", symbol="X")) is False
    assert await _hub().validate_topic(TopicInfo("ticks", symbol="X")) is True  # solo sintaxis


# ------------------------------------------------------- subscribe / seq


async def test_subscribe_entrega_snapshot_seq_1_y_fanout_incrementa() -> None:
    hub = _hub()
    conn = _conn(hub)
    hub.add(conn)

    result, snapshot = await conn._subscribe_one("ticks:EUR/USD")
    assert result == {"topic": "ticks:EUR/USD", "result": "ok"}
    assert snapshot is not None and snapshot["seq"] == 1 and snapshot["data"] is None
    assert conn.topics["ticks:EUR/USD"].seq == 1
    assert hub.connection_count == 1

    hub.publish("ticks:EUR/USD", "tick", {"price": "1.10000000"})
    frames = _drain(conn)
    assert [f["type"] for f in frames] == ["tick"]
    assert frames[0]["seq"] == 2
    assert frames[0]["mode"] == "DEMO"
    assert conn.topics["ticks:EUR/USD"].seq == 2

    # la cache `latest` se actualiza y el delta sigue fluyendo a los suscriptores
    hub.publish("ticks:EUR/USD", "tick", {"price": "1.20000000"})
    assert hub.latest["ticks:EUR/USD"] == {"price": "1.20000000"}
    frames = _drain(conn)
    assert [f["seq"] for f in frames] == [3]


async def test_snapshot_refleja_la_cache_en_una_suscripcion_posterior() -> None:
    hub = _hub()
    conn = _conn(hub)
    hub.add(conn)
    hub.publish("ticks:EUR/USD", "tick", {"price": "1.30000000"})  # nadie escucha aún

    _, snapshot = await conn._subscribe_one("ticks:EUR/USD")
    assert snapshot is not None and snapshot["seq"] == 1
    assert snapshot["data"] == {"price": "1.30000000"}


async def test_subscribe_idempotente_y_limites() -> None:
    hub = _hub(ws_max_subscriptions=1)
    conn = _conn(hub)
    hub.add(conn)

    first, snap1 = await conn._subscribe_one("ticks:EUR/USD")
    second, snap2 = await conn._subscribe_one("ticks:EUR/USD")
    assert first["result"] == second["result"] == "ok"
    assert snap1 is not None and snap2 is None  # re-suscripción no re-snapshotea

    _, over = await conn._subscribe_one("ticks:BTC/USD")
    assert over is None
    result, _ = await conn._subscribe_one("ticks:BTC/USD")
    assert result == {"topic": "ticks:BTC/USD", "result": "topic_limit"}

    # rechazos de catálogo/protocolo con límite de topics holgado
    other = _conn(_hub(), connection_id="c2")
    reserved, _ = await other._subscribe_one("account:123")
    assert reserved == {"topic": "account:123", "result": "forbidden"}
    invalid, _ = await other._subscribe_one("foo")
    assert invalid == {"topic": "foo", "result": "invalid_topic"}
    invalid_tf, _ = await other._subscribe_one("candles:EUR/USD:9m")
    assert invalid_tf == {"topic": "candles:EUR/USD:9m", "result": "invalid_topic"}


async def test_unsubscribe_es_idempotente_y_desacopla_del_hub() -> None:
    hub = _hub()
    conn = _conn(hub)
    hub.add(conn)
    await conn._subscribe_one("ticks:EUR/USD")

    for _ in range(2):
        conn._handle_unsubscribe({"id": "u1", "topics": ["ticks:EUR/USD"]})
    frames = _drain(conn)
    assert all(f["type"] == "ack" and f["id"] == "u1" for f in frames)
    assert conn.topics == {}
    hub.publish("ticks:EUR/USD", "tick", {"price": "1.1"})  # sin suscriptores: solo cache
    assert _drain(conn) == []


# --------------------------------------------------------------- resync


async def test_resync_replay_dentro_del_ring() -> None:
    hub = _hub()
    conn = _conn(hub)
    hub.add(conn)
    await conn._handle_subscribe({"id": "s1", "topics": ["ticks:EUR/USD"]})
    assert [f["type"] for f in _drain(conn)] == ["ack", "snapshot"]
    hub.publish("ticks:EUR/USD", "tick", {"n": 1})
    hub.publish("ticks:EUR/USD", "tick", {"n": 2})
    assert len(_drain(conn)) == 2  # los 2 deltas

    conn._handle_resync({"topic": "ticks:EUR/USD", "from_seq": 1})
    frames = _drain(conn)
    assert frames[0]["type"] == "ack"
    assert frames[0]["results"] == [{"topic": "ticks:EUR/USD", "result": "ok", "replayed": 2}]
    assert [f["seq"] for f in frames[1:]] == [2, 3]


async def test_resync_fuera_del_ring_pide_resync_required() -> None:
    hub = _hub(ws_ring_max_messages=2)
    conn = _conn(hub)
    hub.add(conn)
    await conn._subscribe_one("ticks:EUR/USD")
    for n in (1, 2, 3):
        hub.publish("ticks:EUR/USD", "tick", {"n": n})
    _drain(conn)  # ring queda en [3, 4] (seq 1 y 2 expulsados)

    conn._handle_resync({"topic": "ticks:EUR/USD", "from_seq": 0})  # 1 < oldest(3)
    frames = _drain(conn)
    assert frames[0]["type"] == "resync.required"
    assert frames[0]["from_seq"] == 0

    conn._handle_resync({"topic": "ticks:EUR/USD", "from_seq": 99})  # > seq actual
    assert _drain(conn)[0]["type"] == "resync.required"

    conn._handle_resync({"topic": "ticks:BTC/USD", "from_seq": 0})  # no suscrito
    error = _drain(conn)[0]
    assert error["type"] == "error" and error["code"] == CLOSE_BAD_REQUEST


# ----------------------------------------------------------- backpressure


async def test_backpressure_advisory_y_cierre_4410() -> None:
    hub = _hub(ws_queue_max_frames=4)  # advisory al 70 % ⇒ umbral 2
    conn = _conn(hub)
    hub.add(conn)
    antes_advisories = _metric("ws_backpressure_advisories_total", hub=HUB)
    antes_disconnects = _metric("ws_backpressure_disconnects_total", hub=HUB)

    await conn._handle_subscribe({"id": "s1", "topics": ["ticks:EUR/USD"]})  # ack+snapshot ⇒ advisory (3/4)
    assert not conn._close_event.is_set()

    hub.publish("ticks:EUR/USD", "tick", {"n": 1})  # 4/4: cola llena pero sin error
    assert not conn._close_event.is_set()
    hub.publish("ticks:EUR/USD", "tick", {"n": 2})  # QueueFull ⇒ 4410 sin drenar

    assert conn._close_event.is_set()
    assert conn._close_code == CLOSE_BACKPRESSURE
    assert conn._drain is False
    frames = _drain(conn)
    assert [f["type"] for f in frames] == ["ack", "snapshot", "advisory", "tick"]
    assert frames[2]["code"] == "slow_consumer" and frames[2]["queue_pct"] == 70
    assert _metric("ws_backpressure_advisories_total", hub=HUB) == antes_advisories + 1
    assert _metric("ws_backpressure_disconnects_total", hub=HUB) == antes_disconnects + 1


# ------------------------------------------------------------- protocolo


async def test_tres_violaciones_de_protocolo_cierran_con_4400() -> None:
    conn = _conn(_hub())
    assert conn._fields_ok({"type": "ping"}, "ping") is True
    for _ in range(3):
        assert conn._fields_ok({"type": "ping", "extra": 1}, "ping") is False  # campo desconocido
    assert conn._close_event.is_set() and conn._close_code == CLOSE_BAD_REQUEST

    other = _conn(_hub(), connection_id="c2")
    assert other._fields_ok({"type": "desconocido"}, "desconocido") is False  # tipo no soportado
    assert other.strikes == 1


async def test_ping_del_cliente_respeta_el_intervalo_minimo() -> None:
    conn = _conn(_hub(ws_ping_min_interval_seconds=5.0))
    conn._handle_client_ping()
    frames = _drain(conn)
    assert [f["type"] for f in frames] == ["pong"]

    conn._handle_client_ping()  # demasiado pronto
    error = _drain(conn)[0]
    assert error["type"] == "error" and error["code"] == CLOSE_RATE_LIMITED
    assert conn.strikes == 1


async def test_shutdown_del_hub_cierra_con_1001() -> None:
    hub = _hub()
    conn = _conn(hub)
    hub.add(conn)
    await conn._subscribe_one("ticks:EUR/USD")

    await hub.shutdown()
    assert conn._close_event.is_set() and conn._close_code == CLOSE_GOING_AWAY

    hub.remove(conn)
    assert hub.connection_count == 0
