# ADR-0009 — Identidad de entidades: UUIDv7 para IDs expuestos y formato de correlation_id/causation_id

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **ADR relacionados:** ADR-0004 (headers de traza), ADR-0007 (envelope de eventos), ADR-0010 (Idempotency-Key)

## Contexto

`00-decisions.md` §7 prohíbe IDs secuenciales públicos. Un `serial`/autoincrement expuesto permite a cualquier cliente enumerar recursos (sondear cuántos usuarios u órdenes existen), ordenarlos, detectar crecimientos de negocio y, en algunos casos, adivinar recursos ajenos aprovechando respuestas distintas ante "no existe" vs "no autorizado". Paralelamente, la auditoría y los eventos exigen trazar una request extremo a extremo y saber qué causó qué (`correlation_id`, `causation_id`).

## Decisión

### 1. UUIDv7 para toda entidad expuesta

- **UUIDv7** como identificador de toda entidad expuesta en API, eventos, audit, idempotencia y referencias cruzadas entre servicios: `user_id`, `session_id`, `order_id`, `transaction_id`, `event_id`, `Idempotency-Key`, etc.
- Generación centralizada: una sola implementación en `platform-kernel` (app) y la opción disponible en PostgreSQL 17 para SQL según `O-database-strategy.md` §3; ningún servicio inventa su propio generador.
- El UUIDv7 es monótono por timestamp: conserva el orden por creación y mejora la localidad de índices frente a un v4 aleatorio, sin exponer contadores.
- **Prohibido** usar `serial`/`bigserial`/autoincrement como identificador público. Los ordenes internos (`position` de un asiento, `sort_order`, secuencias de mensajes) no son IDs expuestos y jamás se derivan de ellos; los listados usan **cursor opaco** sobre `(created_at DESC, id DESC)` en lugar de offsets, de modo que ni siquiera el tamaño del conjunto se revela (`Q-api-map.md` §1.4).
- Anti-enumeración: recurso inexistente y no autorizado responden idéntico `404`.

### 2. Formato de correlation_id y causation_id

Ambos son **UUIDv7** y viajan en las mismas formas que los IDs:

| Campo | Significado | Regla de generación | Dónde vive |
|---|---|---|---|
| `request_id` | Identifica una request HTTP concreta | El cliente puede enviarlo (`X-Request-Id`, solo si es UUID); si no, el gateway lo genera y **siempre** lo devuelve | headers, logs, respuestas `problem+json` |
| `correlation_id` | "Esta misma traza extremo a extremo" | UUIDv7 de la request raíz; se propaga sin cambiar en todos los hops | `X-Correlation-Id`, eventos (`correlation_id`), audit, `ledger_transactions.correlation_id` |
| `causation_id` | "Quién me provocó" | `event_id` del evento padre, o `request_id` de la request que originó la acción | envelope de eventos, audit, entradas del ledger |
| `event_id` | Identidad propia del evento | UUIDv7 nuevo por publicación; **nunca** se reutiliza `correlation_id` ni `request_id` | envelope (obligatorio) |

Reglas de cadena:

- Al inicio de una request sin cabecera, el gateway crea `correlation_id` nuevo; si el cliente lo envía y es UUID válido, se respeta (trazas de cliente a servidor).
- Cada hop interno propaga `x-request-id` y `x-correlation-id` (obligatorios, `Q-api-map.md` §3.1).
- Un evento que reacciona a otro evento hereda el `correlation_id` original y pone en `causation_id` el `event_id` que lo desencadenó → cadena acíclica verificable.
- Un trabajo programático (cron, reconciliación, retry de outbox) inicia `correlation_id` propio y usa `causation_id` = `event_id` o job que lo originó; queda documentado en el payload.
- Las tres trazas se registran en `audit` junto con `session_id` y `actor_id` en toda acción crítica.

### 3. Por qué no exponer contadores

- Elimina enumeración masiva y sondeo de recursos ajenos.
- No revela volumen de negocio ni ritmo de altas (competencia, fraude).
- No acopla clientes a un orden numérico que puede cambiar con particiones o migraciones.
- Mantiene estable el contrato aunque internamente existan claves naturales o contadores.

## Consecuencias

### Positivas

- Sin enumeración ni fuga de métricas de negocio por IDs.
- Orden temporal implícito útil para depuración e índices con mejor locality que UUIDv4.
- Trazabilidad total request → evento → asiento → auditoría con un solo vocabulario de identificadores.
- Contractos uniformes: todos los IDs en JSON son strings UUID con el mismo formato.

### Negativas

- IDs de 128 bits poco legibles en logs y tickets de soporte: se mitiga mostrando prefijos en UI y permitiendo buscar por otros campos indexados.
- La generación en aplicación obliga a un helper único y a comprobarlo en tests (riesgo de que un servicio genere v4 por descuido ⇒ test en CI).
- El orden por timestamp sí revela creación aproximada (100 ns de precisión se reducen al truncar): aceptado, no expone conteo.
- Cualquier tabla con secuencial existente deberá migrarse **antes** de exponerse en una API.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **UUIDv4 (aleatorio)** | Sin orden: peor localidad de índice en PostgreSQL y sin aprovechar el orden por creación; se mantiene como válida solo donde no exista v7 disponible, nunca como opción nueva. |
| **ULID** | Prácticamente equivalente en propiedades, pero no es un estándar IETF ni tiene soporte nativo en PostgreSQL; UUIDv7 aporta lo mismo con estandarización. |
| **Secuenciales con salto/prefijo de dominio** | Sigue exponiendo conteo y orden, y permite calcular el siguiente ID. |
| **Snowflake-like (timestamp + worker + secuencia)** | Expone timestamp y worker, requiere coordinación de relojes y no está soportado por el `uuid` de PostgreSQL. |
| **Contadores con ID público separado del interno** | Doble identidad que hay que mantener en todas las tablas, índices y APIs; complejidad sin beneficio frente a UUIDv7. |

## Referencias

- `docs/phase0/00-decisions.md` §7 (sin IDs secuenciales públicos), §8 (envelope con `correlation_id`/`causation_id`).
- `docs/phase0/Q-api-map.md` §1.1 (IDs públicos), §1.4 (paginación por cursor), §1.6 (`X-Request-Id`/`X-Correlation-Id`), §3.1 (propagación interna).
- `docs/phase0/P-event-catalog.md` §1 (envelope canónico).
- `docs/phase0/O-database-strategy.md` §3 (UUIDv7 como tipo canónico).
- `docs/phase0/N-monorepo-structure.md` §5 (convención de nombres: IDs expuestos UUIDv7).
- `docs/adr/ADR-0004-api-first-y-contratos.md`, `docs/adr/ADR-0010-idempotencia-primero.md`.
