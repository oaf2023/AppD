# Runbook 03 — WebSocket `/ws/v1` · **ALCANCE FUTURO (Fase 3)**

> **Fecha:** 2026-09-28 · **Estado del sistema: NO EXISTE.** El streaming WS vive en el servicio `market-data` (Fase 3, BUILD-029) y hoy no hay hub, ni topics, ni AsyncAPI (`services/market-data/asyncapi.yaml` `PENDIENTE`, `component-status.md` §7: *Market data + streaming WS → `PENDIENTE`*).
> **Diseño de referencia:** `phase0/R-websocket-map.md` (única fuente de los valores citados abajo). Este runbook es un **checklist de activación**, no un procedimiento operativo: no ejecutar nada hasta que el hub exista y este encabezado se retire con evidencia.

## 1. Diagnóstico previsto (cuando el hub exista)

| Síntoma | Causa probable (R §§2–5) | Acción |
|---|---|---|
| Cierre `4401` (auth) | Sin frame `auth` en ≤ 5 s, ticket expirado/consumido, token inválido, `auth.expired` | Nuevo ticket `POST /api/v1/auth/ws-tickets` (TTL 30 s, un solo uso) → `auth` → re-suscribir → `resync` |
| Cierre `4403`/`4400` | Topic ajeno/inexistente (respuesta idéntica anti-enumeración) o frame inválido (> 64 KiB, profundidad > 4) | Verificar pertenencia `account_id` ↔ `user_id` y scope; nunca loggear tickets/tokens |
| Cierre `4429` | Rate limit: > 20 frames/s, > 30 `subscribe`/min, > 5 conexiones/usuario, > 50/IP (R §5.3); cierre tras 3 infracciones de control | Backoff + reducir tasa; revisar `ws_auth_failures_total` / `ws_subscribe_denied_total` |
| Cierre `4408` / `advisory heartbeat_degraded` | 2 `pong` perdidos (40 s) | Revisar red/proxy; heartbeats servidor cada 20 s, cliente ≥ 5 s |
| Hueco de `seq` por topic | Paquete perdido / reconexión | `resync {topic, from_seq}` → `snapshot` + deltas; si `resync.required` (fuera del ring buffer 1000 msg / 5 min) ⇒ **backfill REST** con cursor |
| Cierre `4410` backpressure | Cola ≥ 1000 frames o 4 MiB > 10 s | El servidor desconecta (nunca descarta frames críticos); recuperar por snapshot + backfill |

**Reconexión del SDK:** backoff exponencial base 500 ms ×2, máx 30 s, jitter ±20 % → ticket nuevo → `auth` → `subscribe` previos → `resync` por topic (R §3.4). Clientes deduplican por `event_id` (at-least-once).

## 2. Checklist de activación (todo `PENDIENTE` — completar con evidencia antes de operar)

- [ ] Hub `market-data` desplegado + AsyncAPI en `services/market-data/asyncapi.yaml` (contrato único, ADR-0004).
- [ ] Benchmark k6/WS con dataset sintético publicado (BUILD-032); objetivos R §7.1 (`ack` ≤ 200 ms, fan-out p95 ≤ 250 ms local) medidos, no afirmados.
- [ ] Métricas `ws_*` (R §7.2) en Prometheus + alertas mínimas (R §7.3) + dashboards (sin esto, *"nunca alerta sin dashboard y runbook"*).
- [ ] Tests de reconexión sin saltos (`snapshot`+delta, `gap: true` en velas) y de anti-BOLA (`4403` idéntico) en CI.
- [ ] Este runbook actualizado con comandos reales ejecutados en local y este encabezado de alcance futuro retirado.
