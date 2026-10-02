# Runbook 03 — WebSocket `/ws/v1` (hub de `market-data`)

> **Fecha:** 2026-10-02 · **Estado: IMPLEMENTADO (BUILD-029)** — hub en proceso
> (`services/market-data/src/market_data/ws.py`), contrato AsyncAPI en
> `services/market-data/asyncapi.yaml` (fuente de forma de frames) y spec de
> comportamiento en `docs/phase0/R-websocket-map.md`. Este runbook cubre
> diagnóstico, límites y operación del relay outbox; **siguen pendientes** el
> benchmark k6 (BUILD-032), las alertas/dashboards de `ws_*` (R §7.3) y el
> enrutado del gateway hacia `/ws/v1` (hoy los clientes deben llegar al
> puerto de `market-data`, en compose el servicio escucha en el 8084 interno).

## 1. Diagnóstico por síntoma

| Síntoma | Causa probable (R §§2–5) | Acción |
|---|---|---|
| Cierre `4401` (auth) | Sin frame `auth` en ≤ 5 s (`ws_auth_timeout_seconds`), token inválido/caducado, o `auth.expired` durante la sesión | Renovar JWT access (`POST /api/v1/auth/login`) → reconectar → `auth` → re-suscribir → `resync` por topic |
| Cierre `4403` | `Origin` fuera de `ws_allowed_origins` (vacío ⇒ cualquiera) | Corregir el origen del cliente o ampliar la allowlist (variable de entorno) |
| Cierre `4400` | Subprotocolo `v1.platform.json` ausente, JSON inválido/> 64 KiB/profundidad > 4, campos desconocidos o 3 strikes de protocolo | Corregir el cliente; nunca loggear tokens |
| Cierre `4429` | Rate limit: > 20 frames/s o > 60/min, > 30 `subscribe`/min, > 5 conexiones/usuario; cierre tras 3 infracciones (frame `error` previo con `code: 4429`) | Backoff + reducir tasa; revisar `ws_connections_total{result="rate_limited"}` y `ws_auth_failures_total` |
| Cierre `4408` / `advisory heartbeat_degraded` | 2 tandas de `ping` del servidor sin `pong` (intervalo 20 s) | Revisar red/proxy; el cliente debe responder `pong` a cada `ping` |
| Cierre `4404` | Conexión autenticada sin suscripciones durante `ws_idle_timeout_seconds` (120 s) | Suscribir o reconectar |
| Cierre `4410` / `advisory slow_consumer` | Cola de salida ≥ 70 % (advisory) y luego ≥ `ws_queue_max_frames` (1000) | El servidor desconecta (nunca descarta frames críticos); recuperar con `subscribe` + `resync`/backfill REST |
| Hueco de `seq` por topic | Paquete perdido / reconexión | `resync {topic, from_seq}` → `ack {replayed}` + replay del ring; si `resync.required` (fuera del ring: 1000 msg / 300 s) ⇒ **backfill REST** `GET /api/v1/market-data/ticks/{symbol}` o `/candles/{symbol}/{timeframe}` y resuscribir |
| Suscripción denegada (`result: "forbidden"`) | Topic inexistente o prefijo reservado (`account:`, `orders:`, `positions:`, `transactions:`, `notifications:`) — respuesta idéntica anti-BOLA | Verificar símbolo en `GET /api/v1/market-data/symbols`; no enumerar topics |
| Outbox sin publicar (catálogo desactualizado en el hub) | Relay apagado o Redpanda caída | Ver runbook `01-outbox-redpanda.md`; en compose el relay va con `OUTBOX_RELAY_ENABLED=true`; métrica `platform_outbox_backlog{service="market-data"}`, DLQ en `dlq.market.symbols.changed` |

**Reconexión del SDK:** backoff exponencial base 500 ms ×2, máx 30 s, jitter
±20 % → `auth` → `subscribe` previos → `resync` por topic (R §3.4). Clientes
deduplican por `event_id`/`seq` (at-least-once). El modo (`DEMO`/`LIVE`) viaja
en `auth.ok` y en todos los frames de datos.

## 2. Configuración (settings `market_data.config.MarketDataSettings`)

| Variable | Default | Efecto |
|---|---|---|
| `ws_auth_timeout_seconds` | 5.0 | Plazo del primer frame `auth` (si no ⇒ 4401) |
| `ws_heartbeat_interval_seconds` | 20.0 | Cadencia de `ping` del servidor |
| `ws_idle_timeout_seconds` | 120.0 | Cierre 4404 sin suscripciones |
| `ws_ring_max_messages` / `ws_ring_max_age_seconds` | 1000 / 300 | Ring por topic para `resync`; fuera ⇒ `resync.required` |
| `ws_queue_max_frames` | 1000 | Cola por conexión (70 % ⇒ advisory, llena ⇒ 4410) |
| `ws_frames_per_second` / `ws_frames_per_minute` | 20 / 60 | Límites de frames entrantes |
| `ws_subscribe_per_minute` | 30 | Límite de `subscribe` |
| `ws_max_subscriptions` | 50 | Topics por conexión |
| `ws_max_connections_per_user` / `ws_max_connections_per_ip` | 5 / 50 | Conexiones simultáneas |
| `ws_allowed_origins` | vacío | Allowlist de `Origin` (coma-separada) |
| `outbox_relay_enabled` | false | Arranca `OutboxRelay` (compose/CI lo activan) |
| `outbox_relay_interval_ms` / `outbox_max_attempts` / `outbox_batch_size` | 500 / 5 / 100 | Ciclo, intentos antes de DLQ y tamaño de lote |

## 3. Verificación local

- Hub + protocolo + relay: `uv run pytest tests/unit/test_market_data_ws.py tests/integration/test_market_data_ws_hub.py tests/integration/test_market_data_outbox_relay.py`
  (34 tests: handshake/códigos de cierre, snapshot+delta, resync en rango y
  fuera, anti-BOLA, rate limit, límite de conexiones, heartbeat, idle,
  publicación/dlq del outbox en Redpanda real cuando está disponible).
- Contrato de frames: `services/market-data/asyncapi.yaml` (AsyncAPI 2.6.0).
- Backfill REST (para `resync.required`): runbook `Q-api-map` §2.7 /
  `GET /api/v1/market-data/ticks|candles` con JWT `read`.

## 4. Pendientes antes de operar (no verificados aún)

- [ ] Benchmark k6/WS con dataset sintético (BUILD-032); objetivos R §7.1
      (`ack` ≤ 200 ms, fan-out p95 ≤ 250 ms local) **medidos, no afirmados**.
- [ ] Alertas `ws_*` (R §7.3) + dashboards ("nunca alerta sin dashboard y runbook").
- [ ] Enrutado gateway ↔ `/ws/v1` (hoy no existe ruta de gateway al hub).
- [ ] Reconciliación periódica (K §4.4) y consumidor de Redpanda → hub
      (hoy el fan-out es in-process post-commit, `IngestService._publish`).
