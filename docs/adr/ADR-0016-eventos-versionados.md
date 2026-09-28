# ADR-0016 — Eventos versionados con envelope canónico y compatibilidad aditiva

| Campo | Valor |
|---|---|
| **Estado** | Aceptada |
| **Fecha** | 2026-09-27 |
| **Alcance** | productores y consumidores de `*.events` en Redpanda; `packages/platform-contracts` |
| **Fuente canónica** | `docs/phase0/00-decisions.md` §8 · `docs/phase0/P-event-catalog.md` |

## Contexto

- `00-decisions.md` §8 define el envelope mínimo obligatorio (`event_id`, `event_type`, `schema_version`, `aggregate_id`, `aggregate_type`, `timestamp` UTC, `correlation_id`, `causation_id`, `producer`, `payload`) y la publicación mediante transactional outbox (ADR-0007).
- `P-event-catalog.md` detalla 38 eventos con productor, consumidores, agregado, clasificación y criticidad; sin reglas de compatibilidad, una modificación de payload rompería consumidores (`audit`, `wallet`, `risk`) de forma silenciosa.
- La entrega del outbox es **at-least-once**: duplicados y reordenaciones son normales, no excepciones (`P-event-catalog.md` §3.1).
- El evento es también contrato de datos sujeto a gobernanza: clasificación (`CONFIDENTIAL`/`CRITICAL`), retención por tópico (7 años para `ledger.events`, `risk.events`, `payments.events`) y prohibición de PII/secretos innecesarios (`G-security-architecture.md` §7).

## Decisión

1. **Envelope canónico obligatorio** en todo evento, con los campos de `00-decisions.md` §8 más `schema_version` entero incremental. `event_id` es UUIDv7 único global; `timestamp` en UTC RFC3339 con micros; `producer` es el servicio origen. Los payloads se validan con Pydantic en el productor y en el consumidor.
2. **Naming**: `event_type` en PascalCase (`OrderFilled`, `LedgerPosted`) sin versión embebida en el nombre; tópicos por dominio con el patrón `<dominio>.events` (`identity.events`, `ledger.events`, `trading.events`, `risk.events`, `payments.events`) más `*.dlq` para la cola de errores. El registro canónico de tipos es `P-event-catalog.md` y su materialización tipada vive en `packages/platform-contracts`.
3. **Compatibilidad aditiva ("additive only")**: los cambios permitidos son añadir campos `optional` con `default`. Prohibido renombrar, borrar o cambiar el tipo de un campo existente; un campo retirado se mantiene como `null` y se marca `DEPRECATED` en el catálogo. Un cambio incompatibile obliga a nuevo `event_type` (p. ej. `...V2`), práctica a evitar en favor de lo aditivo. Regla verificable: el diff de schemas en CI falla la PR si detecta un cambio no aditivo.
4. **Versionado por `schema_version` (no por fecha de despliegue)**: el consumidor procesa las versiones que conoce; una versión superior desconocida se registra y se salta (o va a DLQ si el payload no es interpretable), y un `event_type` desconocido se ignora con log informativo. Esto permite despliegues independientes por servicio.
5. **Partición por `aggregate_id`**: clave de partición = `aggregate_id` (usuario, cuenta, transacción, depósito/retiro según dominio, ver `P-event-catalog.md` §3.2), de modo que los eventos de un agregado quedan ordenados y en una sola partición. Los consumidores que necesitan orden por cuenta usan el mismo `aggregate_id` como clave.
6. **Entrega at-least-once + consumidor idempotente**: cada consumidor mantiene `consumer_processed_events` con PK `(consumer, event_id)` registrada **en la misma transacción** que su lógica de negocio; si el evento ya existe, se ignora y se confirma. Esto cubre reintentos, reentregas del outbox y reprocessos manuales.
7. **DLQ obligatoria**: deserialización fallida, `schema_version` no soportado con payload irreconocible o fallo tras reintentos con backoff exponencial → tópico `*.dlq` con el envelope original + `error`, `retry_count`, `failed_at`, `consumer` + alerta. Nada se descarta en silencio.
8. **Publicación solo por transactional outbox** (misma transacción ACID que el cambio de estado) con relé que marca `published`; backlog con antigüedad > 60 s es señal de alerta (SLI de `M-tech-stack.md` §7.1).
9. **Contenido mínimo y clasificado**: los eventos llevan solo los datos necesarios (minimización), respetan la clasificación del catálogo y **nunca** incluyen passwords, hashes, secretos, API keys ni PII completa (invariante `00-decisions.md` §7). Los campos personales que sí son imprescindibles (p. ej. email en `UserRegistered`) se revisan contra la política de no-logging antes de promover a evento de producción.
10. **Retención por tópico** según `P-event-catalog.md` §3.5 (p. ej. `ledger.events` 7 años con compacción), con ACLs por productor/consumidor en Redpanda.

## Consecuencias

### Positivas

- Los 13 servicios pueden desplegarse e iterarse de forma independiente: los consumidores no se rompen ante evoluciones aditivas.
- Auditoría y lineage completos: `correlation_id`/`causation_id` permiten seguir una operación desde la API hasta el ledger y el consumidor.
- El orden por agregado y la idempotencia hacen deterministas los flujos de dinero aunque la entrega sea at-least-once (ver ADR-0018: sin ejecuciones duplicadas).
- Replaying histórico desde el log para reconstruir proyecciones o reproducir un incidente.
- DLQ + alerta convierten los fallos de contrato en eventos visibles, no en pérdidas silenciosas.

### Negativas

- El patrón aditivo acumula campos `DEPRECATED` en el payload: los contratos "limpios" requieren ventanas de retiro planificadas.
- Idempotencia por consumidor añade una tabla/índice y un `INSERT` extra en el camino caliente (mitigable con TTL y borrado por rangos sobre UUIDv7).
- At-least-once implica que toda lógica de negocio debe ser idempotente: disciplina extra en cada consumidor nuevo (se automatiza con plantilla y test).
- Particionar por `aggregate_id` puede crear particiones calientes si un agregado es extremadamente activo (p. ej. una cuenta institucional) → a vigilar con métricas de lag por partición.
- Mantener `P-event-catalog.md`, `platform-contracts` y schemas en sincronía exige un gate de CI (diff de contratos) y disciplina de revisión.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| JSON sin `schema_version` (compatibilidad implícita) | Imposible detectar incompatibilidad; los consumidores fallan en producción sin señal temprana. |
| Exactly-once end-to-end (transacciones distribuidas entre productor y consumidor) | Exige coordinación 2PC sobre Redpanda y BDs múltiples: complejidad alta y soporte frágil; la idempotencia del consumidor da el mismo efecto observable. |
| Comunicación síncrona HTTP para todo (sin eventos) | Acoplamiento en tiempo de ejecución, sin replay ni desacople de fallos; contradice el modelo event-driven y el outbox de `A-executive-summary.md` §2. |
| Schema registry externo obligatorio en Fase 1 | `REQUIERE PROVEEDOR`/componente adicional no justificado aún: en Fase 1 el registro es el catálogo + `platform-contracts` con diff en CI; se reevalúa si crece la variedad de schemas. |
| Un tópico global por servicio con eventos de todos los dominios | Pierde ACLs, retenciones y particionado específicos (ledger 7 años vs identity 90 días). |

## Referencias

- `docs/phase0/00-decisions.md` §8 (envelope y outbox), §7 (sin secretos/PII en eventos)
- `docs/phase0/P-event-catalog.md` §1 (envelope), §1.1 (compatibilidad), §3.1–§3.5 (outbox, partición, idempotencia, DLQ, retención)
- `docs/phase0/M-tech-stack.md` §5 (Redpanda), §7.1 (SLI backlog outbox)
- `docs/phase0/G-security-architecture.md` §7 (eventos, ACLs, sin PII), §9 (eventos de seguridad)
- `docs/phase0/N-monorepo-structure.md` §7 (`packages/platform-contracts`)
- ADR-0013 (métricas de outbox/DLQ), ADR-0018 (tests de no-duplicación y reconstrucción)
