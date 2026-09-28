# Runbook 01 — Outbox de `identity` → `audit` vía Redpanda (relay + DLQ)

> **Fecha:** 2026-09-28 · **Servicios:** `identity` (`:8081`) → Redpanda (`:19092`) → `audit` (`:8083`) · **Diseño:** `docs/adr/ADR-0007-eventos-con-outbox.md`, `docs/phase0/P-event-catalog.md`.
> **Estado honesto:** relay `OutboxRelay` y consumidor `AuditEventConsumer` **IMPLEMENTADOS y verificados con Redpanda real** (tests `tests/integration/test_outbox_pipeline.py`). Sin ACLs ni retención de topics (auto-creación del broker) — fuera de BUILD-013.

## 1. Cómo funciona hoy (verificado en código)

1. Cada cambio de estado en `identity` inserta una fila en `identity.outbox_events` **en la misma transacción** (ADR-0007 §1). Columnas reales (`services/identity/src/identity/models.py`): `id` (=`event_id`), `event_type`, `schema_version`, `aggregate_type`, `aggregate_id`, `payload`, `correlation_id`, `causation_id`, `producer`, `created_at`, `published_at` (NULL = pendiente), `publish_attempts`, `next_attempt_at`, `last_error`, `dead_lettered_at` (NULL = no dead-lettered).
2. `OutboxRelay` (`services/identity/src/identity/outbox.py`) sondea cada `outbox_relay_interval_ms` (**500 ms** por defecto), selecciona hasta `outbox_batch_size` (**100**) filas con `published_at IS NULL AND dead_lettered_at IS NULL AND (next_attempt_at IS NULL OR next_attempt_at <= now)`, ordenadas por `created_at`.
3. Publicación con `AIOKafkaProducer` (`acks=all`) a topic `topic_for_event(...)` (p. ej. `identity.user.registered`), **clave = `aggregate_id`** (orden por agregado), payload = envelope canónico JSON.
4. Éxito ⇒ `published_at = utcnow()`, `last_error = NULL`. La marca es en una transacción **distinta** de la de dominio (at-least-once; `audit` deduplica por `event_id`).
5. Fallo ⇒ `publish_attempts += 1`, `last_error` (≤ 2000 chars) y `next_attempt_at = now + backoff` (`compute_backoff_ms`: exponencial `base·2^n` acotado a **60 s** con **jitter ±25 %**). Un fallo de conexión invalida el sender y cortocircuita el resto del ciclo.
6. Tras `outbox_max_attempts` (**5**) fallos ⇒ el evento se envía a la DLQ **`dlq.<topic-original>`** con `{"dlq_reason": "max_attempts_exceeded", "original_topic", "attempts", "last_error", "envelope"}` y la fila queda `dead_lettered_at = now()` (excluida del poller; `published_at` sigue NULL).
7. `AuditEventConsumer` (`services/audit/src/audit/consumer.py`) consume los `PHASE1_TOPICS` con consumer group **`audit-service`**, `enable_auto_commit=False`: commit **solo tras persistir** en `audit.records` (dedup por `event_id`); envelope inválido ⇒ log sin payload + commit (skip); fallo de insert ⇒ sin commit y reconexión a los 5 s.
8. Métricas (visibles en `GET /metrics`): `platform_outbox_backlog{service}`, `platform_outbox_published_total{service}`, `platform_outbox_dead_lettered_total{service}`.

## 2. Diagnóstico de backlog (SQL directo)

```powershell
# Contenedores (PostgreSQL :5433, Redpanda :19092)
docker compose -f infrastructure/compose/compose.yml --profile events up -d postgres redis redpanda

# Pendientes (ni publicados ni dead-lettered), antigüedad y errores recientes
docker compose -f infrastructure/compose/compose.yml exec postgres psql -U platform -d platform_identity `
  -c "SELECT event_type, count(*) AS pendientes, max(now() - created_at) AS mas_antiguo, max(publish_attempts) AS max_intentos FROM identity.outbox_events WHERE published_at IS NULL AND dead_lettered_at IS NULL GROUP BY 1 ORDER BY 2 DESC;"

# Fila concreta con error
docker compose -f infrastructure/compose/compose.yml exec postgres psql -U platform -d platform_identity `
  -c "SELECT id, event_type, publish_attempts, next_attempt_at, left(last_error, 200), created_at FROM identity.outbox_events WHERE published_at IS NULL AND dead_lettered_at IS NULL ORDER BY created_at LIMIT 20;"

# Backlog / DLQ en la UI de métricas
curl -s http://localhost:8081/metrics | Select-String "platform_outbox"
```

- **Backlog > 60 s sostenido** = breach del SLO (`M-tech-stack.md` §7.1) ⇒ escalar según §4 y registrar incidente.
- **Causas típicas:** broker caído (mirar logs de `identity`, `"publicación del outbox fallida"`), relay deshabilitado (`OUTBOX_RELAY_ENABLED=false`) o consumidor caído (los eventos sí se publican, pero `audit` no avanza ⇒ revisar group `audit-service`).

## 3. Operación con Redpanda

```powershell
docker compose -f infrastructure/compose/compose.yml --profile events up -d redpanda
docker compose -f infrastructure/compose/compose.yml exec redpanda rpk topic list --brokers redpanda:9092
docker compose -f infrastructure/compose/compose.yml exec redpanda rpk topic consume dlq.identity.user.registered --brokers redpanda:9092 --num 20
docker compose -f infrastructure/compose/compose.yml exec redpanda rpk group describe audit-service --brokers redpanda:9092   # lag del consumidor
```

## 4. Configuración (env)

| Variable | Servicio | Defecto | Efecto |
|---|---|---|---|
| `REDPANDA_BOOTSTRAP_SERVERS` | identity y audit | `localhost:19092` | brokers |
| `OUTBOX_RELAY_ENABLED` | identity | `true` | desactiva el relay (solo tests/dev) |
| `OUTBOX_RELAY_INTERVAL_MS` | identity | `500` | cadencia del poll (y base del backoff) |
| `OUTBOX_MAX_ATTEMPTS` | identity | `5` | intentos antes de DLQ |
| `OUTBOX_BATCH_SIZE` | identity | `100` | tamaño máximo de batch |
| `EVENT_CONSUMER_ENABLED` | audit | `true` | desactiva el consumidor |

## 5. Replay de fila atascada o dead-lettered

- **Intento normal:** nada que hacer manualmente — el relay reintenta solo según `next_attempt_at`.
- **Tras DLQ (incidente documentado):** corregir la causa (broker, configuración) y republicar **con el mismo `event_id`** (el consumidor deduplica):

```powershell
docker compose -f infrastructure/compose/compose.yml exec postgres psql -U platform -d platform_identity `
  -c "UPDATE identity.outbox_events SET publish_attempts = 0, next_attempt_at = NULL, dead_lettered_at = NULL, last_error = NULL WHERE id = '<uuid>';"
```

- **Purga por retención** (ADR-0007): eliminar solo filas `published` (o `dead_lettered_at` ya auditadas) fuera de retención; **jamás** pendientes. `PENDIENTE` de job y umbral — no ejecutar a mano sin incidente registrado.

## 6. Verificación en código (enlaces)

- `services/identity/src/identity/outbox.py` — `OutboxRelay.relay_once()`, `compute_backoff_ms()`, `KafkaEventSender`.
- `services/identity/migrations/versions/0002_outbox_relay.py` — columnas de reintento/DLQ.
- `services/audit/src/audit/consumer.py`, `services/audit/src/audit/ingest.py` — consumidor + dedup.
- `packages/platform-contracts/src/platform_contracts/events.py` — `topic_for_event()`, `dlq_topic()`, `PHASE1_TOPICS`.
- Tests: `tests/unit/test_outbox_relay.py` (6), `tests/integration/test_outbox_pipeline.py` (3, requieren Redpanda).
