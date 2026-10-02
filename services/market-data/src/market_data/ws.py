"""ws — hub WebSocket interno `/ws/v1` (R-websocket-map, BUILD-029).

Difusión + suscripción **solo** (REST manda para comandos y backfill, R §1);
ninguna mutación financiera por WS. Subprotocolo obligatorio `v1.platform.json`.

Semántica de `seq`/`resync` (decisión BUILD-029 sobre R §3.2/§5.1): `seq`
monotónico **por conexión-topic**, base 1 (snapshot = 1); el ring buffer vive
en la conexión. `resync {topic, from_seq}` con el rango aún en el ring ⇒ `ack`
+ replay de deltas `from_seq+1..latest` con sus `seq` originales; fuera del
ring (o `from_seq` > `seq`) ⇒ `resync.required` (backfill REST + re-suscribe ⇒
snapshot nuevo, `seq` = 1). Tras reconexión no hay continuidad sin snapshot.

Cierre accept-then-close: se acepta siempre el handshake y el resultado se
comunica con código WS — `4400` protocolo · `4401` auth · `4403` origin ·
`4404` idle sin suscripciones · `4408` heartbeat · `4410` backpressure ·
`4429` rate limit · `1001` apagado del hub.

Límites (R §5.3, settings `ws_*`): frames entrantes 20/s y 60/min (3
infracciones ⇒ cierre 4429), `subscribe` 30/min (`ack rate_limited`), 50
suscripciones por conexión (`ack topic_limit`), 5 conexiones por usuario y 50
por IP (cierre 4429), ping de cliente ≥ 5 s (`4429` de control). Autenticación:
primer frame `{"type":"auth","access_token":…}` en `ws_auth_timeout_seconds`
(fallback R §2.2 — `POST /api/v1/auth/ws-tickets` es `PENDIENTE` en identity).

Backpressure (R §5.2): cola `asyncio.Queue` por conexión; advisory
`slow_consumer` al 70 % y cierre `4410` con cola llena (sin descartar frames
selectivamente). Heartbeat: `ping` cada `ws_heartbeat_interval_seconds`, 1 fallo
→ advisory `heartbeat_degraded`, 2 → cierre `4408`; sin suscripciones >
`ws_idle_timeout_seconds` → cierre `4404`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket
from platform_kernel.clock import utcnow
from platform_kernel.config import get_settings as get_kernel_settings
from platform_kernel.ratelimit import InMemoryRateLimiter
from platform_kernel.security.tokens import TOKEN_TYPE_ACCESS, TokenError, decode_jwt

from market_data.config import MarketDataSettings
from market_data.metrics import (
    HUB_NAME,
    WS_AUTH_FAILURES,
    WS_BACKPRESSURE_ADVISORIES,
    WS_BACKPRESSURE_DISCONNECTS,
    WS_CONNECTIONS_ACTIVE,
    WS_CONNECTIONS_TOTAL,
    WS_DISCONNECTS,
    WS_HEARTBEAT_TIMEOUTS,
    WS_MESSAGES_RECV,
    WS_MESSAGES_SENT,
    WS_RESYNC_REQUESTS,
    WS_SUBSCRIBE_DENIED,
    WS_SUBSCRIPTIONS_ACTIVE,
)

logger = logging.getLogger("market_data.ws")

#: Subprotocolo de frames JSON (R §1); sin él ⇒ cierre 4400.
SUBPROTOCOL = "v1.platform.json"

CLOSE_BAD_REQUEST = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_IDLE = 4404
CLOSE_HEARTBEAT_TIMEOUT = 4408
CLOSE_BACKPRESSURE = 4410
CLOSE_RATE_LIMITED = 4429
CLOSE_GOING_AWAY = 1001

#: Violaciones de protocolo/rate limit antes de cerrar (R §5.3, §6).
MAX_STRIKES = 3
#: Advisory de cola llena (R §5.2: ≥ 70 %).
ADVISORY_PCT = 70
#: Profundidad máxima del JSON de cliente (R §3.2).
MAX_FRAME_DEPTH = 4
#: Tópicos por mensaje `subscribe`/`unsubscribe`.
MAX_TOPICS_PER_MESSAGE = 100

SYSTEM_TOPIC = "system:announcements"
TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "4h", "1d"})
#: Prefijos de tópicos reservados de fases posteriores: respuesta idéntica
#: `forbidden` (anti-enumeración, R §2.3).
RESERVED_PREFIXES = ("account:", "orders:", "positions:", "transactions:", "notifications:")

_DISCONNECT_BY_CODE: dict[int, str] = {
    CLOSE_BAD_REQUEST: "protocol",
    CLOSE_UNAUTHORIZED: "auth_expired",
    CLOSE_FORBIDDEN: "origin",
    CLOSE_IDLE: "idle",
    CLOSE_HEARTBEAT_TIMEOUT: "heartbeat_timeout",
    CLOSE_BACKPRESSURE: "backpressure",
    CLOSE_RATE_LIMITED: "rate_limit",
    CLOSE_GOING_AWAY: "server_shutdown",
}

TopicValidator = Callable[["TopicInfo"], Awaitable[bool]]


def _consume_task_result(task: asyncio.Task[Any]) -> None:
    """Evita el warning de asyncio por excepciones no recogidas en tareas WS."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning(
            "tarea WS terminó con error",
            extra={"extra_fields": {"task": task.get_name(), "error": f"{type(exc).__name__}: {exc}"}},
        )


@dataclass(frozen=True, slots=True)
class TopicInfo:
    """Topic canónico parseado (`ticks`/`candles`/`system`)."""

    pattern: str
    symbol: str | None = None
    timeframe: str | None = None


def parse_topic(topic: str) -> TopicInfo | None:
    """Parsea un topic canónico; `None` si es sintácticamente inválido."""
    if topic == SYSTEM_TOPIC:
        return TopicInfo("system")
    parts = topic.split(":")
    if len(parts) == 2 and parts[0] == "ticks" and _valid_symbol(parts[1]):
        return TopicInfo("ticks", symbol=parts[1])
    if len(parts) == 3 and parts[0] == "candles" and _valid_symbol(parts[1]) and parts[2] in TIMEFRAMES:
        return TopicInfo("candles", symbol=parts[1], timeframe=parts[2])
    return None


def is_reserved_topic(topic: str) -> bool:
    return topic.startswith(RESERVED_PREFIXES)


def _valid_symbol(symbol: str) -> bool:
    return bool(symbol) and len(symbol) <= 32 and ":" not in symbol and not symbol.startswith(" ")


def _depth_ok(value: Any, depth: int = 1) -> bool:
    if depth > MAX_FRAME_DEPTH:
        return False
    if isinstance(value, dict):
        return all(_depth_ok(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        return all(_depth_ok(item, depth + 1) for item in value)
    return True


def _strings_ok(value: Any, max_len: int) -> bool:
    if isinstance(value, str):
        return len(value) <= max_len
    if isinstance(value, dict):
        return all(_strings_ok(item, max_len) for item in value.values()) and all(len(key) <= max_len for key in value)
    if isinstance(value, list):
        return all(_strings_ok(item, max_len) for item in value)
    return True


#: Campos permitidos por tipo de mensaje (JSON estricto, campos desconocidos → 4400).
_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "auth": frozenset({"type", "access_token"}),
    "subscribe": frozenset({"type", "id", "topics"}),
    "unsubscribe": frozenset({"type", "id", "topics"}),
    "resync": frozenset({"type", "topic", "from_seq"}),
    "ping": frozenset({"type"}),
    "pong": frozenset({"type"}),
}


@dataclass(slots=True)
class RingItem:
    seq: int
    at: float
    frame: dict[str, Any]


@dataclass(slots=True)
class TopicState:
    """Estado por conexión-topic: `seq` monotónico + ring buffer (R §5.1)."""

    topic: str
    pattern: str
    seq: int = 0
    ring: deque[RingItem] = field(default_factory=deque)

    def prune(self, *, max_messages: int, max_age_seconds: int, now: float) -> None:
        while self.ring and now - self.ring[0].at > max_age_seconds:
            self.ring.popleft()
        while len(self.ring) > max_messages:
            self.ring.popleft()


class Connection:
    """Conexión WS: auth en primer frame, cola de salida, ring y controles."""

    def __init__(self, hub: MarketHub, websocket: WebSocket, *, connection_id: str, client_ip: str) -> None:
        self.hub = hub
        self.ws = websocket
        self.settings = hub.settings
        self.connection_id = connection_id
        self.client_ip = client_ip
        self.mode = hub.mode
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self.settings.ws_queue_max_frames)
        self.advisory_threshold = max(1, self.settings.ws_queue_max_frames * ADVISORY_PCT // 100)
        self.topics: dict[str, TopicState] = {}
        self.limiter = InMemoryRateLimiter()
        self.strikes = 0
        self.authenticated = False
        self.user_id: str | None = None
        self.roles: tuple[str, ...] = ()
        self.auth_expires_at: float | None = None
        self._auth_deadline: float = 0.0
        self._started_at: float = 0.0
        self.last_activity: float = 0.0
        self.last_client_ping: float = 0.0
        self._next_ping_at: float | None = None
        self._pong_deadline: float | None = None
        self._misses = 0
        self._advisory_active = False
        self._close_event = asyncio.Event()
        self._close_code: int | None = None
        self._close_reason = ""
        self._drain = True
        self.disconnect_reason: str | None = None

    # ------------------------------------------------------------------ frames

    def _frame(self, frame_type: str, **fields: Any) -> dict[str, Any]:
        frame: dict[str, Any] = {"type": frame_type, "ts": utcnow().isoformat(), "mode": self.mode}
        frame.update(fields)
        return frame

    def enqueue(self, frame: dict[str, Any]) -> bool:
        """Encola un frame saliente; cola llena ⇒ cierre 4410 (R §5.2)."""
        WS_MESSAGES_SENT.labels(HUB_NAME, str(frame.get("topic", "control")), str(frame["type"])).inc()
        try:
            self.queue.put_nowait(frame)
        except asyncio.QueueFull:
            WS_BACKPRESSURE_DISCONNECTS.labels(HUB_NAME).inc()
            self.request_close(CLOSE_BACKPRESSURE, "cola de salida llena", drain=False)
            return False
        depth = self.queue.qsize()
        if depth >= self.advisory_threshold and not self._advisory_active:
            self._advisory_active = True
            WS_BACKPRESSURE_ADVISORIES.labels(HUB_NAME).inc()
            with contextlib.suppress(asyncio.QueueFull):
                self.queue.put_nowait(self._frame("advisory", code="slow_consumer", queue_pct=ADVISORY_PCT))
        elif depth < self.advisory_threshold and self._advisory_active:
            self._advisory_active = False
        return True

    def deliver(self, topic: str, frame_type: str, data: dict[str, Any] | None, ts: datetime) -> None:
        """Fan-out del hub: asigna `seq` de esta conexión-topic y encola."""
        state = self.topics.get(topic)
        if state is None:
            return
        state.seq += 1
        frame = {
            "type": frame_type,
            "topic": topic,
            "seq": state.seq,
            "ts": ts.isoformat(),
            "mode": self.mode,
            "data": data,
        }
        state.ring.append(RingItem(state.seq, time.monotonic(), frame))
        state.prune(
            max_messages=self.settings.ws_ring_max_messages,
            max_age_seconds=self.settings.ws_ring_max_age_seconds,
            now=time.monotonic(),
        )
        self.enqueue(frame)

    def request_close(self, code: int, reason: str = "", *, drain: bool = True) -> None:
        if self._close_event.is_set():
            return
        self._close_code = code
        self._close_reason = reason
        self._drain = drain
        self.disconnect_reason = _DISCONNECT_BY_CODE.get(code, "client")
        self._close_event.set()

    # ------------------------------------------------------------------ serve

    async def serve(self) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        self._auth_deadline = now + self.settings.ws_auth_timeout_seconds
        self._started_at = now
        self.last_activity = now
        reader = asyncio.create_task(self._reader_loop(), name=f"ws-reader-{self.connection_id}")
        sender = asyncio.create_task(self._sender_loop(), name=f"ws-sender-{self.connection_id}")
        timer = asyncio.create_task(self._timer_loop(), name=f"ws-timer-{self.connection_id}")
        tasks = [reader, sender, timer]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            # Sin `await gather` aquí: si la cancelación llega mientras se
            # drena, `gather` relanza un `CancelledError()` sin mensaje y el
            # scope cancelador no puede absorberlo (rompe el exit de TestClient).
            # Las tareas se cancelan y se resuelven solas en el siguiente tick.
            self._close_event.set()
            for task in tasks:
                task.cancel()
                task.add_done_callback(_consume_task_result)

    async def _sender_loop(self) -> None:
        """Único consumidor de la cola y único escritor sobre el socket."""
        get_task: asyncio.Task[dict[str, Any]] = asyncio.ensure_future(self.queue.get())
        try:
            while True:
                close_task = asyncio.ensure_future(self._close_event.wait())
                done, _ = await asyncio.wait({get_task, close_task}, return_when=asyncio.FIRST_COMPLETED)
                close_task.cancel()
                if get_task in done:
                    frame = get_task.result()
                    get_task = asyncio.ensure_future(self.queue.get())
                    await self.ws.send_json(frame)
                    continue
                if self._drain and not self.queue.empty():
                    continue
                break
        finally:
            get_task.cancel()
            if self._close_code is not None:
                with contextlib.suppress(Exception):
                    await self.ws.close(self._close_code, reason=self._close_reason or None)

    async def _timer_loop(self) -> None:
        settings = self.settings
        tick = max(0.02, min(1.0, settings.ws_auth_timeout_seconds / 2, settings.ws_heartbeat_interval_seconds / 2))
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(tick)
            now = loop.time()
            if self._close_event.is_set():
                return
            if not self.authenticated:
                if now >= self._auth_deadline:
                    WS_AUTH_FAILURES.labels(HUB_NAME, "timeout").inc()
                    WS_CONNECTIONS_TOTAL.labels(HUB_NAME, "auth_failed").inc()
                    self.request_close(CLOSE_UNAUTHORIZED, "timeout de autenticación")
                    return
                continue
            if self.auth_expires_at is not None and time.time() >= self.auth_expires_at:
                self.enqueue(self._frame("auth.expired"))
                self.request_close(CLOSE_UNAUTHORIZED, "token de acceso expirado")
                return
            # Miss check ANTES de emitir el siguiente ping: ambos coinciden en
            # el mismo tick y rearmar primero el deadline anularía el fallo.
            if self._pong_deadline is not None and now >= self._pong_deadline:
                self._pong_deadline = None
                self._misses += 1
                if self._misses == 1:
                    self.enqueue(self._frame("advisory", code="heartbeat_degraded"))
                elif self._misses >= 2:
                    WS_HEARTBEAT_TIMEOUTS.labels(HUB_NAME).inc()
                    self.request_close(CLOSE_HEARTBEAT_TIMEOUT, "2 pings sin pong")
                    return
            if self._next_ping_at is not None and now >= self._next_ping_at:
                self._next_ping_at = now + settings.ws_heartbeat_interval_seconds
                self.enqueue(self._frame("ping"))
                self._pong_deadline = now + settings.ws_heartbeat_interval_seconds
            if not self.topics and now - self.last_activity >= settings.ws_idle_timeout_seconds:
                self.request_close(CLOSE_IDLE, "sin suscripciones")
                return

    # ----------------------------------------------------------------- reader

    async def _reader_loop(self) -> None:
        settings = self.settings
        while True:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            self.last_activity = time.monotonic()
            raw = message.get("text")
            if raw is None:
                self._protocol_error("frame binario no soportado")
                continue
            if len(raw.encode("utf-8")) > settings.ws_frame_max_bytes:
                self._protocol_error("frame mayor que ws_frame_max_bytes")
                continue
            if not await self._within_frame_limits():
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                self._protocol_error("JSON inválido")
                continue
            if not isinstance(msg, dict):
                self._protocol_error("el frame debe ser un objeto JSON")
                continue
            if not _depth_ok(msg):
                self._protocol_error("profundidad máxima de JSON excedida")
                continue
            if not _strings_ok(msg, settings.ws_string_max_bytes):
                self._protocol_error("cadena de texto demasiado larga")
                continue
            kind = msg.get("type")
            WS_MESSAGES_RECV.labels(HUB_NAME, kind if isinstance(kind, str) else "unknown").inc()
            if not self.authenticated:
                if kind == "auth":
                    if self._fields_ok(msg, kind):
                        self._handle_auth(msg)
                else:
                    # R §2.1: sin auth nunca se habla de tópicos
                    self.request_close(CLOSE_UNAUTHORIZED, "auth requerida antes que cualquier mensaje")
                continue
            if not self._fields_ok(msg, kind):
                continue
            if kind == "subscribe":
                await self._handle_subscribe(msg)
            elif kind == "unsubscribe":
                self._handle_unsubscribe(msg)
            elif kind == "resync":
                self._handle_resync(msg)
            elif kind == "ping":
                self._handle_client_ping()
            elif kind == "pong":
                self._misses = 0
                self._pong_deadline = None
            # _fields_ok ya rechazó tipos desconocidos

    async def _within_frame_limits(self) -> bool:
        settings = self.settings
        per_second = await self.limiter.hit("frames_s", settings.ws_frames_per_second, 1)
        if not per_second.allowed:
            return await self._rate_limited()
        per_minute = await self.limiter.hit("frames_m", settings.ws_frames_per_minute, 60)
        if not per_minute.allowed:
            return await self._rate_limited()
        return True

    async def _rate_limited(self) -> bool:
        self.enqueue(self._frame("error", code=CLOSE_RATE_LIMITED, message="rate limit de frames entrantes"))
        self.strikes += 1
        if self.strikes >= MAX_STRIKES:
            self.request_close(CLOSE_RATE_LIMITED, "3 infracciones de rate limit")
            return False
        # la infracción no procesa el frame (R §5.3)
        return False

    def _fields_ok(self, msg: dict[str, Any], kind: Any) -> bool:
        if not isinstance(kind, str) or kind not in _ALLOWED_FIELDS:
            self._protocol_error(f"tipo de mensaje no soportado: {kind!r}")
            return False
        extra = set(msg) - _ALLOWED_FIELDS[kind]
        if extra:
            self._protocol_error(f"campos desconocidos: {sorted(extra)}")
            return False
        if kind in ("subscribe", "unsubscribe"):
            msg_id = msg.get("id")
            topics = msg.get("topics")
            if not isinstance(msg_id, str) or not msg_id or len(msg_id) > 128:
                self._protocol_error("id debe ser string (1..128)")
                return False
            if not isinstance(topics, list) or not topics or len(topics) > MAX_TOPICS_PER_MESSAGE:
                self._protocol_error("topics debe ser lista no vacía (≤100)")
                return False
            if not all(isinstance(topic, str) for topic in topics):
                self._protocol_error("topics solo admite strings")
                return False
        elif kind == "resync":
            topic = msg.get("topic")
            from_seq = msg.get("from_seq")
            if not isinstance(topic, str) or not topic:
                self._protocol_error("topic debe ser string no vacío")
                return False
            if not isinstance(from_seq, int) or isinstance(from_seq, bool) or from_seq < 0:
                self._protocol_error("from_seq debe ser entero ≥ 0")
                return False
        elif kind == "auth":
            token = msg.get("access_token")
            if not isinstance(token, str) or not token:
                self._protocol_error("access_token debe ser string no vacío")
                return False
        return True

    def _protocol_error(self, detail: str) -> None:
        self.enqueue(self._frame("error", code=CLOSE_BAD_REQUEST, message=detail))
        self.strikes += 1
        if self.strikes >= MAX_STRIKES:
            self.request_close(CLOSE_BAD_REQUEST, "3 violaciones de protocolo")

    # ------------------------------------------------------------- control msg

    def _handle_auth(self, msg: dict[str, Any]) -> None:
        token = msg["access_token"]
        kernel = get_kernel_settings()
        try:
            claims = decode_jwt(
                token,
                secret=kernel.jwt_secret,
                issuer=kernel.jwt_issuer,
                audience=kernel.jwt_audience,
                expected_type=TOKEN_TYPE_ACCESS,
            )
        except TokenError as exc:
            cause = "expired" if "caducado" in str(exc) else "invalid"
            WS_AUTH_FAILURES.labels(HUB_NAME, cause).inc()
            WS_CONNECTIONS_TOTAL.labels(HUB_NAME, "auth_failed").inc()
            self.request_close(CLOSE_UNAUTHORIZED, "token de acceso inválido")
            return
        user_id = str(claims["sub"])
        if self.hub.user_connections(user_id) >= self.settings.ws_max_connections_per_user:
            WS_CONNECTIONS_TOTAL.labels(HUB_NAME, "rate_limited").inc()
            self.request_close(CLOSE_RATE_LIMITED, "límite de conexiones por usuario")
            return
        self.authenticated = True
        self.user_id = user_id
        self.roles = tuple(claims.get("roles") or ())
        self.auth_expires_at = float(claims["exp"])
        self._next_ping_at = time.monotonic() + self.settings.ws_heartbeat_interval_seconds
        WS_CONNECTIONS_TOTAL.labels(HUB_NAME, "ok").inc()
        WS_CONNECTIONS_ACTIVE.labels(HUB_NAME, self.mode).inc()
        self.enqueue(
            self._frame(
                "auth.ok",
                connection_id=self.connection_id,
                user_id=user_id,
                scopes=list(self.roles),
                expires_at=datetime.fromtimestamp(float(claims["exp"]), tz=UTC).isoformat(),
            )
        )

    async def _handle_subscribe(self, msg: dict[str, Any]) -> None:
        topics: list[str] = msg["topics"]
        rate = await self.limiter.hit("subscribe", self.settings.ws_subscribe_per_minute, 60)
        if not rate.allowed:
            results = [{"topic": topic, "result": "rate_limited"} for topic in topics]
            snapshots: list[dict[str, Any]] = []
        else:
            outcomes = [await self._subscribe_one(topic) for topic in topics]
            results = [item[0] for item in outcomes]
            snapshots = [item[1] for item in outcomes if item[1] is not None]
        # orden de entrega: `ack` primero y luego los snapshots (decisión 029)
        self.enqueue(self._frame("ack", id=msg["id"], results=results))
        for snapshot in snapshots:
            self.enqueue(snapshot)

    async def _subscribe_one(self, topic: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Valida y suscribe; devuelve (resultado, snapshot a entregar)."""
        if topic in self.topics:
            return {"topic": topic, "result": "ok"}, None  # idempotente, sin re-snapshot
        if len(self.topics) >= self.settings.ws_max_subscriptions:
            WS_SUBSCRIBE_DENIED.labels(HUB_NAME, "topic_limit").inc()
            return {"topic": topic, "result": "topic_limit"}, None
        if is_reserved_topic(topic):
            # respuesta idéntica para inexistente y ajeno (anti-BOLA, R §2.3)
            WS_SUBSCRIBE_DENIED.labels(HUB_NAME, "forbidden").inc()
            return {"topic": topic, "result": "forbidden"}, None
        info = parse_topic(topic)
        if info is None:
            return {"topic": topic, "result": "invalid_topic"}, None
        if not await self.hub.validate_topic(info):
            WS_SUBSCRIBE_DENIED.labels(HUB_NAME, "forbidden").inc()
            return {"topic": topic, "result": "forbidden"}, None
        state = TopicState(topic=topic, pattern=info.pattern)
        self.topics[topic] = state
        self.hub.attach(self, topic, info.pattern)
        state.seq = 1
        snapshot = {
            "type": "snapshot",
            "topic": topic,
            "seq": 1,
            "ts": utcnow().isoformat(),
            "mode": self.mode,
            "data": self.hub.latest.get(topic),
        }
        state.ring.append(RingItem(1, time.monotonic(), snapshot))
        return {"topic": topic, "result": "ok"}, snapshot

    def _handle_unsubscribe(self, msg: dict[str, Any]) -> None:
        results: list[dict[str, Any]] = []
        for topic in msg["topics"]:
            state = self.topics.pop(topic, None)
            if state is not None:
                self.hub.detach(self, topic, state.pattern)
            results.append({"topic": topic, "result": "ok"})  # idempotente
        self.enqueue(self._frame("ack", id=msg["id"], results=results))

    def _handle_resync(self, msg: dict[str, Any]) -> None:
        topic: str = msg["topic"]
        from_seq: int = msg["from_seq"]
        state = self.topics.get(topic)
        if state is None:
            self.enqueue(self._frame("error", code=CLOSE_BAD_REQUEST, message="topic no suscrito", topic=topic))
            return
        now = time.monotonic()
        state.prune(
            max_messages=self.settings.ws_ring_max_messages,
            max_age_seconds=self.settings.ws_ring_max_age_seconds,
            now=now,
        )
        oldest = state.ring[0].seq if state.ring else state.seq + 1
        if from_seq > state.seq or from_seq + 1 < oldest:
            WS_RESYNC_REQUESTS.labels(HUB_NAME, "buffer_expired").inc()
            self.enqueue(self._frame("resync.required", topic=topic, from_seq=from_seq))
            return
        WS_RESYNC_REQUESTS.labels(HUB_NAME, "gap").inc()
        replay = [item.frame for item in state.ring if item.seq > from_seq]
        self.enqueue(
            self._frame(
                "ack",
                topic=topic,
                results=[{"topic": topic, "result": "ok", "replayed": len(replay)}],
            )
        )
        for frame in replay:
            self.enqueue(frame)

    def _handle_client_ping(self) -> None:
        now = time.monotonic()
        if now - self.last_client_ping < self.settings.ws_ping_min_interval_seconds:
            self.enqueue(self._frame("error", code=CLOSE_RATE_LIMITED, message="ping demasiado frecuente"))
            self.strikes += 1
            if self.strikes >= MAX_STRIKES:
                self.request_close(CLOSE_RATE_LIMITED, "3 pings demasiado frecuentes")
            return
        self.last_client_ping = now
        self._misses = 0
        self._pong_deadline = None
        self.enqueue(self._frame("pong"))


class MarketHub:
    """Registro de conexiones, fan-out por topic y cache de snapshot."""

    def __init__(self, settings: MarketDataSettings, *, topic_validator: TopicValidator | None = None) -> None:
        self.settings = settings
        self.mode = settings.ws_mode
        #: último `data` publicado por topic (snapshot en subscribe, R §5.1)
        self.latest: dict[str, dict[str, Any] | None] = {}
        self._connections: set[Connection] = set()
        self._subs: dict[str, set[Connection]] = {}
        self._topic_validator = topic_validator

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def add(self, conn: Connection) -> None:
        self._connections.add(conn)

    def remove(self, conn: Connection) -> None:
        if conn not in self._connections:
            return
        self._connections.discard(conn)
        for topic, state in list(conn.topics.items()):
            self.detach(conn, topic, state.pattern)
        if conn.authenticated:
            WS_CONNECTIONS_ACTIVE.labels(HUB_NAME, self.mode).dec()
        WS_DISCONNECTS.labels(HUB_NAME, conn.disconnect_reason or "client").inc()
        logger.info(
            "conexión WS cerrada",
            extra={
                "extra_fields": {
                    "connection_id": conn.connection_id,
                    "reason": conn.disconnect_reason or "client",
                    "authenticated": conn.authenticated,
                }
            },
        )

    def ip_connections(self, client_ip: str) -> int:
        return sum(1 for conn in self._connections if conn.client_ip == client_ip)

    def user_connections(self, user_id: str) -> int:
        return sum(1 for conn in self._connections if conn.authenticated and conn.user_id == user_id)

    def attach(self, conn: Connection, topic: str, pattern: str) -> None:
        self._subs.setdefault(topic, set()).add(conn)
        WS_SUBSCRIPTIONS_ACTIVE.labels(HUB_NAME, pattern).inc()

    def detach(self, conn: Connection, topic: str, pattern: str) -> None:
        subscribers = self._subs.get(topic)
        if subscribers is None or conn not in subscribers:
            return
        subscribers.discard(conn)
        if not subscribers:
            self._subs.pop(topic, None)
        WS_SUBSCRIPTIONS_ACTIVE.labels(HUB_NAME, pattern).dec()

    def publish(self, topic: str, frame_type: str, data: dict[str, Any] | None) -> None:
        """Fan-out in-process: cache + deltas a los suscriptores (post-commit)."""
        self.latest[topic] = data
        ts = utcnow()
        for conn in tuple(self._subs.get(topic, ())):
            conn.deliver(topic, frame_type, data, ts)

    async def validate_topic(self, info: TopicInfo) -> bool:
        if self._topic_validator is None:
            return True  # solo validación sintáctica (tests unitarios)
        return bool(await self._topic_validator(info))

    async def shutdown(self) -> None:
        for conn in tuple(self._connections):
            conn.request_close(CLOSE_GOING_AWAY, "apagado del hub")


ws_router = APIRouter()


@ws_router.websocket("/ws/v1")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Handshake `/ws/v1`: subprotocolo → origin → límite IP → auth (R §2)."""
    hub: MarketHub = websocket.app.state.hub
    settings = hub.settings
    offered = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    accept_proto = SUBPROTOCOL if SUBPROTOCOL in offered else None
    await websocket.accept(subprotocol=accept_proto)
    if accept_proto is None:
        WS_CONNECTIONS_TOTAL.labels(HUB_NAME, "bad_subprotocol").inc()
        WS_DISCONNECTS.labels(HUB_NAME, "protocol").inc()
        with contextlib.suppress(Exception):
            await websocket.close(CLOSE_BAD_REQUEST, reason="subprotocolo v1.platform.json requerido")
        return
    origin = websocket.headers.get("origin")
    if settings.ws_allowed_origins_list and origin and origin not in settings.ws_allowed_origins_list:
        WS_CONNECTIONS_TOTAL.labels(HUB_NAME, "origin_rejected").inc()
        WS_DISCONNECTS.labels(HUB_NAME, "origin").inc()
        with contextlib.suppress(Exception):
            await websocket.close(CLOSE_FORBIDDEN, reason="origin no permitido")
        return
    client_ip = websocket.client.host if websocket.client else "unknown"
    if hub.ip_connections(client_ip) >= settings.ws_max_connections_per_ip:
        WS_CONNECTIONS_TOTAL.labels(HUB_NAME, "rate_limited").inc()
        WS_DISCONNECTS.labels(HUB_NAME, "rate_limit").inc()
        with contextlib.suppress(Exception):
            await websocket.close(CLOSE_RATE_LIMITED, reason="límite de conexiones por IP")
        return
    conn = Connection(hub, websocket, connection_id=uuid.uuid4().hex, client_ip=client_ip)
    hub.add(conn)
    try:
        await conn.serve()
    finally:
        hub.remove(conn)


__all__ = [
    "CLOSE_BACKPRESSURE",
    "CLOSE_BAD_REQUEST",
    "CLOSE_FORBIDDEN",
    "CLOSE_GOING_AWAY",
    "CLOSE_HEARTBEAT_TIMEOUT",
    "CLOSE_IDLE",
    "CLOSE_RATE_LIMITED",
    "CLOSE_UNAUTHORIZED",
    "SUBPROTOCOL",
    "SYSTEM_TOPIC",
    "TIMEFRAMES",
    "Connection",
    "MarketHub",
    "TopicInfo",
    "is_reserved_topic",
    "parse_topic",
    "websocket_endpoint",
    "ws_router",
]
