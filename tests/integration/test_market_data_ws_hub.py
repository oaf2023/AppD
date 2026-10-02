"""Pruebas de integración del hub WebSocket `/ws/v1` — ASGI real (BUILD-029, R §2/§3/§5).

`TestClient` ejecuta el lifespan real (migraciones sobre `platform_market_data`)
y el hub en su portal; la ingestión se dispara a mano sobre
`app.state.ingest_service` con reloj controlado, igual que en
`test_market_data_persistence.py`. Cobertura: handshake (4400/4403), auth
(4401 por token y por timeout), catálogo anti-BOLA, snapshot → delta con `seq`
contiguo, reconexión sin saltos (snapshot refleja la cache), `resync` en rango
y fuera del ring, heartbeat 4408, idle 4404, rate limit 4429 y límite de
conexiones por usuario.
"""

from __future__ import annotations

import os
import uuid
from contextlib import ExitStack
from datetime import datetime

import psycopg
import pytest
from helpers import TEST_JWT_SECRET, TEST_POSTGRES_DSN
from market_data.config import MarketDataSettings
from market_data.main import create_app
from market_data.normalization import RawTick
from platform_kernel.clock import utcnow
from platform_kernel.security.tokens import new_access_token
from prometheus_client import REGISTRY
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

pytestmark = pytest.mark.integration

SYMBOL = "EUR/USD"
SUBPROTOCOL = "v1.platform.json"
TOPIC = f"ticks:{SYMBOL}"
BASE_SETTINGS: dict[str, object] = {
    "environment": "test",
    "ws_auth_timeout_seconds": 1.0,
    # sin pings ni idle durante la prueba salvo donde se explícita lo contrario
    "ws_heartbeat_interval_seconds": 30.0,
    "ws_idle_timeout_seconds": 300.0,
    "ws_ping_min_interval_seconds": 0.0,
}


@pytest.fixture(autouse=True)
def ws_schema(clean_dbs: None):  # type: ignore[no-untyped-def]
    """Migra `platform_market_data` y limpia ticks/velas entre pruebas."""
    from market_data.db import reset_engine
    from market_data.migrate import run_migrations

    reset_engine()
    run_migrations(os.environ["MARKET_DATA_DATABASE_URL"])
    with (
        psycopg.connect(f"{TEST_POSTGRES_DSN} dbname=platform_market_data", autocommit=True) as conn,
        conn.cursor() as cur,
    ):
        cur.execute("DELETE FROM market_data.ticks")
        cur.execute("DELETE FROM market_data.candles")
    yield
    reset_engine()


def _client(**overrides: object) -> TestClient:
    settings = MarketDataSettings(**{**BASE_SETTINGS, **overrides})  # type: ignore[arg-type]
    return TestClient(create_app(settings=settings))


def _token(*, user_id: str | None = None) -> str:
    return new_access_token(
        user_id=user_id or str(uuid.uuid4()),
        session_id=str(uuid.uuid4()),
        roles=["user"],
        secret=TEST_JWT_SECRET,
        issuer="platform-identity",
        audience="platform-api",
        ttl_seconds=900,
    )


def _connect(client: TestClient) -> WebSocketTestSession:
    return client.websocket_connect("/ws/v1", subprotocols=[SUBPROTOCOL])


def _auth(ws: WebSocketTestSession, token: str | None = None) -> dict:
    ws.send_json({"type": "auth", "access_token": token or _token()})
    frame = ws.receive_json()
    assert frame["type"] == "auth.ok", frame
    return frame


def _subscribe(ws: WebSocketTestSession, *topics: str, sub_id: str = "s1") -> dict:
    ws.send_json({"type": "subscribe", "id": sub_id, "topics": list(topics)})
    return ws.receive_json()


def _raw(price: str, *, ts: datetime, symbol: str = SYMBOL) -> RawTick:
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


def _ingest(client: TestClient, raws: list[RawTick], *, now: datetime) -> None:
    """Dispara la ingestión real en el loop del portal (fan-out incluido)."""
    service = client.app.state.ingest_service
    client.portal.call(lambda: service.ingest_raw(raws, now=now))


def _close_code_after(ws: WebSocketTestSession, *, limit: int = 12) -> tuple[int | None, list[dict]]:
    """Lee hasta el cierre; devuelve (código, frames recibidos)."""
    frames: list[dict] = []
    for _ in range(limit):
        try:
            frames.append(ws.receive_json())
        except WebSocketDisconnect as exc:
            return exc.code, frames
    return None, frames


# ------------------------------------------------------------------ handshake


def test_handshake_sin_subprotocolo_cierra_4400() -> None:
    with _client() as client:
        with client.websocket_connect("/ws/v1") as ws, pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4400


def test_origin_no_permitido_cierra_4403() -> None:
    with _client(ws_allowed_origins="https://app.example") as client:
        with (
            client.websocket_connect(
                "/ws/v1", subprotocols=[SUBPROTOCOL], headers={"Origin": "https://evil.example"}
            ) as ws,
            pytest.raises(WebSocketDisconnect) as exc,
        ):
            ws.receive_json()
        assert exc.value.code == 4403


def test_auth_invalido_cierra_4401_y_cuenta_la_metrica() -> None:
    labels = {"hub": "market-data", "cause": "invalid"}
    before = REGISTRY.get_sample_value("ws_auth_failures_total", labels) or 0.0
    with _client() as client, _connect(client) as ws:
        ws.send_json({"type": "auth", "access_token": "no-es-un-jwt"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    assert (REGISTRY.get_sample_value("ws_auth_failures_total", labels) or 0.0) == before + 1


def test_auth_timeout_cierra_4401() -> None:
    with _client(ws_auth_timeout_seconds=0.3) as client, _connect(client) as ws:
        # sin frame `auth`: el temporizador cierra con 4401
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_auth_ok_entrega_subprotocolo_y_modo_demo() -> None:
    with _client() as client, _connect(client) as ws:
        assert ws.accepted_subprotocol == SUBPROTOCOL
        frame = _auth(ws)
        assert frame["mode"] == "DEMO"
        assert frame["scopes"] == ["user"]
        assert frame["user_id"] and frame["connection_id"] and frame["expires_at"]


def test_ping_del_cliente_responde_pong() -> None:
    with _client() as client, _connect(client) as ws:
        _auth(ws)
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


# ------------------------------------------------------- subscribe / fan-out


def test_subscribe_snapshot_y_delta_tras_ingest() -> None:
    with _client() as client, _connect(client) as ws:
        _auth(ws)
        ack = _subscribe(ws, TOPIC)
        assert ack["type"] == "ack" and ack["id"] == "s1"
        assert ack["results"] == [{"topic": TOPIC, "result": "ok"}]
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["seq"] == 1 and snap["data"] is None

        now = utcnow()
        _ingest(client, [_raw("1.10100000", ts=now)], now=now)
        tick = ws.receive_json()
        assert tick["type"] == "tick"
        assert tick["seq"] == 2  # contiguo: snapshot=1, delta=2
        assert tick["mode"] == "DEMO"
        assert tick["data"]["price"] == "1.10100000"
        assert tick["data"]["simulated"] is True


def test_fanout_de_velas_por_timeframe_1m_y_5m() -> None:
    """BUILD-030: cada timeframe tiene su topic `candles:{symbol}:{tf}`."""
    from market_data.store import bucket_start

    with _client() as client:
        with _connect(client) as ws:
            _auth(ws)
            ack1 = _subscribe(ws, f"candles:{SYMBOL}:1m", sub_id="c1")
            assert ack1["results"] == [{"topic": f"candles:{SYMBOL}:1m", "result": "ok"}]
            snap1 = ws.receive_json()
            assert snap1["type"] == "snapshot" and snap1["data"] is None

            ack5 = _subscribe(ws, f"candles:{SYMBOL}:5m", sub_id="c2")
            assert ack5["results"] == [{"topic": f"candles:{SYMBOL}:5m", "result": "ok"}]
            snap5 = ws.receive_json()
            assert snap5["type"] == "snapshot" and snap5["data"] is None

            now = utcnow()
            _ingest(client, [_raw("1.10100000", ts=now)], now=now)

            candle1 = ws.receive_json()  # orden de publicación: TIMEFRAMES (1m antes que 5m)
            candle5 = ws.receive_json()
            # seq es por topic: cada vela continúa la snapshot de su propio topic
            assert candle1["seq"] == snap1["seq"] + 1
            assert candle5["seq"] == snap5["seq"] + 1
            assert candle1["type"] == "candle" and candle5["type"] == "candle"
            assert candle1["data"]["timeframe"] == "1m"
            assert candle5["data"]["timeframe"] == "5m"
            assert candle1["data"]["ts"] == bucket_start(now, "1m").isoformat()
            assert candle5["data"]["ts"] == bucket_start(now, "5m").isoformat()
            assert candle1["data"]["open"] == "1.10100000" and candle1["data"]["close"] == "1.10100000"
            assert candle1["data"]["volume"] is None  # _raw sin tamaño ⇒ volume NULL
            assert candle1["data"]["gap"] is False and candle1["data"]["simulated"] is True

        # la reconexión ve la última vela publicada (estado, no vacío)
        with _connect(client) as ws2:
            _auth(ws2)
            _subscribe(ws2, f"candles:{SYMBOL}:5m")
            snap = ws2.receive_json()
            assert snap["data"]["timeframe"] == "5m" and snap["data"]["gap"] is False


def test_topics_reservados_y_desconocidos_forbidden_anti_bola() -> None:
    with _client() as client, _connect(client) as ws:
        _auth(ws)
        ack = _subscribe(ws, "account:123", TOPIC, "ticks:NOSUCH", "foo", "orders:9", sub_id="mix")
        results = {row["topic"]: row["result"] for row in ack["results"]}
        assert results == {
            "account:123": "forbidden",
            TOPIC: "ok",
            "ticks:NOSUCH": "forbidden",  # existe la sintaxis, no el símbolo
            "foo": "invalid_topic",
            "orders:9": "forbidden",
        }
        snap = ws.receive_json()  # solo el topic `ok` genera snapshot
        assert snap["topic"] == TOPIC


def test_reconexion_snapshot_refleja_estado_sin_saltos() -> None:
    """La cache `latest` cierra el hueco: la reconexión arranca desde el estado."""
    with _client() as client:
        with _connect(client) as ws1:
            _auth(ws1)
            _subscribe(ws1, TOPIC)
            assert ws1.receive_json()["data"] is None
            now_a = utcnow()
            _ingest(client, [_raw("1.10000000", ts=now_a)], now=now_a)
            tick_a = ws1.receive_json()
            assert tick_a["seq"] == 2 and tick_a["data"]["price"] == "1.10000000"
        # ws1 desconectada: el tick B llega sin suscriptores → solo actualiza cache

        now_b = utcnow()
        _ingest(client, [_raw("1.20000000", ts=now_b)], now=now_b)

        with _connect(client) as ws2:
            _auth(ws2)
            _subscribe(ws2, TOPIC)
            snap = ws2.receive_json()
            assert snap["seq"] == 1  # seq base 1 en la conexión nueva
            assert snap["data"]["price"] == "1.20000000"  # estado fresco, sin retroceso
            now_c = utcnow()
            _ingest(client, [_raw("1.30000000", ts=now_c)], now=now_c)
            tick_c = ws2.receive_json()
            assert tick_c["seq"] == 2 and tick_c["data"]["price"] == "1.30000000"


def test_resync_replay_dentro_del_ring_y_fuera_resync_required() -> None:
    with _client(ws_ring_max_messages=2) as client, _connect(client) as ws:
        _auth(ws)
        _subscribe(ws, TOPIC)
        assert ws.receive_json()["seq"] == 1

        now = utcnow()
        _ingest(
            client,
            [
                _raw("1.10010000", ts=now),
                _raw("1.10020000", ts=now),
                _raw("1.10030000", ts=now),
            ],
            now=now,
        )
        seqs = [ws.receive_json()["seq"] for _ in range(3)]
        assert seqs == [2, 3, 4]  # ring con max=2 ⇒ sólo [3,4] sobrevive

        ws.send_json({"type": "resync", "topic": TOPIC, "from_seq": 0})
        required = ws.receive_json()
        assert required["type"] == "resync.required" and required["from_seq"] == 0

        ws.send_json({"type": "resync", "topic": TOPIC, "from_seq": 3})
        ack = ws.receive_json()
        assert ack["type"] == "ack"
        assert ack["results"] == [{"topic": TOPIC, "result": "ok", "replayed": 1}]
        replayed = ws.receive_json()
        assert replayed["seq"] == 4


# ------------------------------------------------------------------ controles


def test_heartbeat_dos_pings_sin_pong_cierran_4408() -> None:
    with _client(ws_heartbeat_interval_seconds=0.2) as client, _connect(client) as ws:
        _auth(ws)
        code, frames = _close_code_after(ws)
        assert code == 4408
        assert any(f.get("code") == "heartbeat_degraded" for f in frames)


def test_sin_suscripciones_idle_cierra_4404() -> None:
    with _client(ws_idle_timeout_seconds=0.3) as client, _connect(client) as ws:
        _auth(ws)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4404


def test_rate_limit_de_frames_cierra_4429() -> None:
    settings = {
        "ws_frames_per_second": 1,
        "ws_frames_per_minute": 1000,
    }
    with _client(**settings) as client, _connect(client) as ws:
        _auth(ws)  # consume la franja del segundo actual
        for _ in range(8):  # margen ante un posible rollo de ventana
            ws.send_json({"type": "ping"})
        code, frames = _close_code_after(ws, limit=16)
        errors = [f for f in frames if f["type"] == "error" and f.get("code") == 4429]
        assert code == 4429
        assert len(errors) >= 3  # 3 infracciones ⇒ cierre


def test_limite_de_conexiones_por_usuario_cierra_4429() -> None:
    token = _token(user_id="usuario-limite")
    with _client() as client, ExitStack() as stack:
        for _ in range(5):
            ws = stack.enter_context(_connect(client))
            _auth(ws, token)
        sixth = stack.enter_context(_connect(client))
        sixth.send_json({"type": "auth", "access_token": token})
        with pytest.raises(WebSocketDisconnect) as exc:
            sixth.receive_json()
        assert exc.value.code == 4429
