# ADR-0007 — Eventos con transactional outbox y Redpanda (API Kafka)

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **ADR relacionados:** ADR-0004 (contratos de eventos), ADR-0005 (datos), ADR-0010 (idempotencia)

## Contexto

La plataforma es event-driven: `audit` consume eventos de seguridad, `wallet` proyecta balances desde `LedgerPosted`, `trading` y `risk` reaccionan a ejecuciones. `00-decisions.md` §5 exige consistencia fuerte en dinero: el estado cambia en una transacción ACID y los eventos deben publicarse de forma fiable **después**. Publicar directamente desde el código (commit → publicar → ack) falla en ambos sentidos: si el commit muere antes de publicar, el evento se pierde; si la publicación muere antes del commit, se emite un evento fantasma que hace creer a los consumidores que hubo un cambio inexistente.

Sobre la tecnología del log existen alternativas razonables: publicar directamente, NATS JetStream, Kafka puro, colas simples (Redis Streams/RabbitMQ) o CDC sobre la outbox.

## Decisión

### 1. Transactional outbox (obligatorio en todo servicio)

- Cada servicio tiene su tabla `outbox_events` en **su propio schema**; se inserta en la **misma transacción ACID** que el cambio de estado.
- Un relay/poller publica en batch (`WHERE NOT published ORDER BY created_at`), envía a Redpanda y marca `published=true` en una transacción distinta (nunca en la del dominio).
- Garantía **at-least-once** → todo consumidor debe ser idempotente (deduplicación por `event_id`, `P-event-catalog.md` §3.3).
- Envelope canónico: `event_id` (UUIDv7), `event_type`, `schema_version`, `aggregate_id`, `aggregate_type`, `timestamp` UTC, `correlation_id`, `causation_id`, `producer`, `payload`. Topic: `<dominio>.<entidad>.<evento>`.
- Partición por `aggregate_id` para garantizar orden por agregado (login→MFA→sesión; orden→ejecución por cuenta).
- Fallos: retry con backoff, **DLQ** por tópico, métrica de backlog. SLO: 0 eventos sin publicar con antigüedad > 60 s (`M-tech-stack.md` §7.1).
- Prohibido publicar "a mano" tras hacer commit (test BUILD-013: evento no pareado a su transacción ⇒ falla el CI).

### 2. Transporte: Redpanda (API Kafka)

Log duradero con replay, reintentos y compatibilidad con el ecosistema Kafka; binario único sin JVM → compose y CI más ligeros que Kafka puro. ACLs por productor/consumidor; nunca datos sensibles en payloads (passwords, tokens, PII completa).

### 3. Criterios de conmutación (ej. a NATS JetStream u otro)

La conmutación **exige un ADR nuevo** y se plantea solo si se cumple alguna condición medida:

| # | Criterio |
|---|---|
| 1 | Latencia p95 de publicación del relay > 1 s sostenido tras optimizar batch/tamaño, o backlog recurrente fuera del SLO de 60 s. |
| 2 | Necesidad real de semántica de request/reply o fan-out por sujetos que el log no cubre de forma razonable. |
| 3 | Coste operativo medido de Redpanda (memoria/CPU en compose o K8s) por encima del umbral aceptado por el equipo. |
| 4 | Pérdida de soporte/compatibilidad del binario o de la API usada. |

Para que el cambio sea barato, el dominio solo conoce las interfaces `EventPublisher`/`EventConsumer` de `platform-kernel` y el contrato de los eventos (`platform-contracts`): el conmutador reescribe adapters y consumidores, no los productores de negocio.

## Consecuencias

### Positivas

- Cero eventos perdidos y cero eventos fantasma: el evento y su cambio de estado son inseparables.
- Replay histórico para re-procesar consumidores o reconstruir proyecciones.
- Consumidores desacoplados y añadibles sin tocar al productor (audit, notification, reporting).
- Orden por agregado garantizado por partición; DLQ y métricas dan operabilidad.
- Redpanda evita el peso operativo de Kafka manteniendo su API.

### Negativas

- Retraso entre commit y publicación (polling): los consumidores ven el cambio con segundos de retraso; se acepta porque ningún camino de dinero depende de latencia sub-segundo entre servicios.
- At-least-once implica reintentos y deduplicación obligatoria en cada consumidor (duplicados si se olvida).
- La outbox crece y hay que purgarla (`published` + retención) para no degradar el índice del poller.
- Dos sistemas que operar (PostgreSQL + Redpanda) y DLQs que alguien debe vigilar.
- Operativa de Kafka menos difundida que la de colas simples: runbooks y métricas de lag son obligatorios.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **Publicación directa tras commit** | Pierde eventos si el proceso muere entre commit y publicación y emite eventos fantasma si falla el commit; inaceptable para dinero y auditoría. |
| **NATS JetStream** | Más simple y ligero, pero menor valor de replay histórico y menor ecosistema de conectores/monitoring compatibles con Kafka; migrar después reescribiría consumidores. Se conserva como destino posible si se cumplen los criterios de conmutación. |
| **Kafka puro (Apache)** | Mismo modelo, pero JVM + partes múltiples (broker, connect, schema registry) elevan el coste operativo y el arranque en compose/CI de una Fase 1 con pocos tópicos. |
| **Redis Streams / RabbitMQ** | Fácil de montar, pero semántica de replay, retención y consumidores múltiples más débil para outbox + auditoría con varios consumidores. |
| **CDC sobre la outbox (Debezium u homólogo)** | Evita el polling y baja la latencia de publicación; se reserva como evolución si el relay no cumple los criterios de latencia, manteniendo el mismo patrón de outbox. |
| **Cola simple entre servicios sin log** | Sin replay ni orden verificable; los eventos de auditoría pierden su valor forense. |

## Referencias

- `docs/phase0/00-decisions.md` §5 (consistencia fuerte + outbox), §8 (envelope y catálogo).
- `docs/phase0/P-event-catalog.md` §1 (envelope), §3.1 (outbox), §3.2 (partición), §3.3 (idempotencia de consumidor).
- `docs/phase0/M-tech-stack.md` §5 (Redpanda) y §5.1 (alternativas descartadas).
- `docs/phase0/N-monorepo-structure.md` §9 regla 6 (solo outbox).
- `docs/phase0/W-build-now.md` BUILD-013 (outbox), DLQ/backoff.
- `docs/adr/ADR-0004-api-first-y-contratos.md`, `docs/adr/ADR-0005-base-de-datos-por-servicio.md`, `docs/adr/ADR-0010-idempotencia-primero.md`.
