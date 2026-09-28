# ADR-0010 — Idempotencia primero: Idempotency-Key + hash de solicitud + respuesta almacenada + expiración

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **ADR relacionados:** ADR-0004 (headers y versionado), ADR-0005 (ledger), ADR-0009 (formato de la clave)

## Contexto

Los clientes reintentan (timeout, corte de red, refresh de PWA), los gateways reenvían, los PSPs reenvían webhooks y los relés de outbox publican al menos una vez. En dinero, un reintento mal manejado significa un depósito dos veces, un retiro pagado dos veces o un asiento duplicado. `00-decisions.md` §5 declara la idempotencia obligatoria en orders, payments, withdrawals, deposits, webhooks y ledger postings. Un constraint único local no cubre todos los flujos ni el replay de una respuesta ya emitida.

## Decisión

Patrón canónico **`Idempotency-Key` + hash de solicitud + respuesta almacenada + expiración**, implementado en `platform-kernel` y usado por cada servicio sobre su **propia base PostgreSQL** (Redis no es almacén de idempotencia: perder datos por reinicio implicaría doble efecto).

### 1. Contrato HTTP

| Regla | Detalle |
|---|---|
| Cabecera | `Idempotency-Key: <uuidv7>`; ausente en una ruta obligatoria ⇒ `400 VALIDATION_ERROR` |
| Alcance | La clave es válida solo para el trío **(ruta, método, sujeto autenticado)**: evita colisiones entre actores |
| Persistencia | `(key, subject, route, request_hash, state, status, response_body, created_at, expires_at)` |
| Hash | SHA-256 del payload **canonizado** (JSON normalizado: claves ordenadas, sin campos no deterministas del cliente); la serialización canónica se documenta y se congela: cambiarla rompe la compatibilidad de reintentos |
| Mismo hash | Devuelve la respuesta almacenada con el **mismo status** + cabecera `Idempotent-Replay: true` |
| Hash distinto | `409 IDEMPOTENCY_KEY_REUSE` con `problem+json` y fecha del uso original |
| En curso | `409 IDEMPOTENCY_IN_PROGRESS` + `Retry-After: 1` |
| Expiración | TTL **24 h** por defecto (configurable por entorno), purga por job + índice; audit de cada replay en `audit` con `request_id`, `correlation_id` e `idempotency_key` |

### 2. Concurrencia

- **Registro de la clave y efecto en la misma transacción** cuando el efecto es local: `INSERT … ON CONFLICT (idempotency_key) DO NOTHING` actúa de lock de entrada; el ganador ejecuta, los concurrentes reciben `409 IDEMPOTENCY_IN_PROGRESS`.
- En `ledger` la clave vive en `ledger_idempotency_keys` dentro de la transacción ACID del asiento: o se escribe la transacción completa con su outbox, o no se escribe nada.
- En flujos multi-servicio la clave se **propaga** en los headers internos (`Q-api-map.md` §3.1): el efecto aguas abajo usa la misma clave, de modo que un reintento no crea un segundo efecto en el servicio siguiente.
- El estado del recurso se mantiene idempotente por sí mismo (cancelar dos veces la misma orden ⇒ `200`/`409` documentado, nunca doble efecto).

### 3. Cobertura obligatoria

Toda mutación financiera, verificable con test en CI que falte la cabecera donde es obligatoria:

- `orders` (create, patch, cancel, cancel-all, batch) y `positions/{id}/close`
- `deposits`, `withdrawals` (create, cancel), `wallet/transfers`
- **ledger postings** (`POST /internal/v1/postings`) y `payments/holds|release`
- **webhooks entrantes**: primero verificación de firma HMAC y ventana temporal, después idempotencia con la clave de entrega del proveedor → los reintentos del PSP producen **un solo asiento**
- `reports` (jobs), rutas de identidad marcadas `Idem=Sí` (`verify-email`, `logout`, `password/*`, API keys)

### 4. Límites de la protección

La idempotencia **no sustituye**: la deduplicación de consumidores de eventos por `event_id` (ADR-0007), la validación de máquina de estados del recurso, ni la verificación de firma de webhooks. Son capas complementarias.

## Consecuencias

### Positivas

- Efecto único garantizado bajo reintentos de cliente, gateway, PSP y consumidores: sin depósitos ni asientos duplicados.
- Los clientes pueden reintentar sin miedo y los PSPs pueden reenviar webhooks libremente.
- Replay auditable: la respuesta original es reproducible y queda registrada.
- Mismo patrón en todos los flujos financieros: una sola implementación testeada en `platform-kernel`.

### Negativas

- Una fila extra por mutación financiera y un coste de purge/retención que hay que operar.
- Latencia adicional (~1 insert/select) en el camino caliente de escritura.
- El hash canónico exige estabilidad de serialización: un cambio aparentemente inofensivo en el orden de campos o en el formato decimal rompe los reintentos en vuelo.
- La respuesta almacenada ocupa espacio: hay que limitar su tamaño y no guardar cuerpos gigantes (exportaciones ⇒ referencia al job, no el contenido).
- Alguien debe auditar que las rutas nuevas obligatorias no se queden sin cabecera: se automatiza en CI.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **Solo constraint único en `client_order_id`** | Cubre órdenes, no webhooks, transfers, postings ni jobs; y no devuelve la respuesta original almacenada. |
| **"Exactly-once" del broker** | No existe como garantía real: los brokers dan at-least-once o best-effort; la unicidad se resuelve en la aplicación. |
| **Reintentos con backoff sin clave** | El reintento vuelve a ejecutar el efecto: inaceptable con dinero. |
| **Idempotencia solo en Redis** | Rápida, pero Redis no es fuente de verdad: un reinicio borra las claves y habilita doble efecto. Se descarta para flujos financieros. |
| **Deduplicación solo en el consumidor** | No evita el doble efecto en el servicio que ejecuta la operación; solo mitiga el duplicado de eventos. |

## Referencias

- `docs/phase0/00-decisions.md` §5 (idempotencia obligatoria y mecanismo).
- `docs/phase0/Q-api-map.md` §1.8 (reglas), §1.6 (cabeceras), §2 (tabla de rutas `Idem`), §3.1 (propagación interna).
- `docs/phase0/L-ledger-architecture.md` §1 y modelo (`ledger_idempotency_keys`).
- `docs/phase0/O-database-strategy.md` §6.1 (check-then-insert con `ON CONFLICT`).
- `docs/phase0/G-security-architecture.md` §8.3, §11.1 (gate: idempotencia sin duplicados en replay).
- `docs/adr/ADR-0005-base-de-datos-por-servicio.md`, `docs/adr/ADR-0007-eventos-con-outbox.md`, `docs/adr/ADR-0009-identidad-y-ids.md`.
