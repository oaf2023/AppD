# ADR-0005 — Base de datos por servicio: un schema PostgreSQL propio, sin acceso cruzado; ledger como subdominio inmutable

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **ADR relacionados:** ADR-0002 (descomposición), ADR-0006 (dinero), ADR-0007 (eventos), ADR-0010 (idempotencia)

## Contexto

Trece servicios comparten una única instancia PostgreSQL 17 en Fase 1 (compose local). Si todos comparten tablas o schemas con permisos amplios, el aislamiento de dominio se convierte en convención y no en control: cualquier servicio puede leer/escribir datos de otro, los joins ocultos aparecen en los repositorios y el cambio de schema de un servicio rompe a otros sin previo aviso. Para dinero, además, la única fuente de verdad debe ser un ledger double-entry append-only verificable (`L-ledger-architecture.md`).

## Decisión

### 1. Un schema PostgreSQL por servicio

- Schema = nombre de servicio (`identity`, `audit`, `market_data`, `ledger`, …), usuario por servicio (`<servicio>_svc`) con `GRANT USAGE, CREATE ON SCHEMA <svc>` + `DEFAULT PRIVILEGES` (`O-database-strategy.md` §2).
- `search_path` fijado al schema propio en cada conexión; las migraciones Alembic son **cadenas propias** por servicio (`services/<svc>/alembic.ini` + `migrations/`) sin orden compartido entre servicios.
- **Prohibido el acceso cruzado a tablas**: ningún servicio consulta, escribe, crea una vista, una FK o un join hacia el schema de otro. Comunicación **solo** por API versionada (`/api/v1`, `/internal/v1`) y eventos Redpanda (ADR-0007).
- Verificación en CI: un test de integración intenta consultar el schema ajeno con el usuario del servicio y **debe fallar**; ruff/import-linter impiden los imports de código entre servicios.
- Cada servicio migra el suyo como job init antes del rollout (nunca "al arrancar el servidor" en varias réplicas); expand/migrate/contract y compatibilidad con N-1 (`N-monorepo-structure.md` §8).

### 2. Ledger como subdominio con modelo inmutable propio

El servicio `ledger` (Fase 2, schema `ledger`) es la **única fuente de verdad financiera** y tiene su propio modelo, no reutiliza tablas de otros servicios:

- **Double-entry**: cada transacción afecta a ≥2 cuentas con `Σ débitos = Σ créditos` (constraint `CHECK` + validación en aplicación).
- **Append-only**: `REVOKE UPDATE, DELETE` sobre `ledger_entries`/`ledger_transactions` + triggers anti-modificación; correcciones solo por transacción de reversión (`reverses_tx_id` / `reverses_entry_id`), nunca `UPDATE` ni `DELETE`.
- **Inmutable y auditable**: `created_at` + hash encadenado opcional (SHA-256 de fila anterior + actual), `correlation_id`/`causation_id` en toda transacción.
- **Idempotente**: tabla `ledger_idempotency_keys` (`key`, `request_hash`, `transaction_id`, `response`, `expires_at`) escrita en la misma transacción ACID que el asiento (ver ADR-0010).
- **Transaccional con eventos**: asiento y fila de `outbox_events` se insertan en la misma transacción (ADR-0007).
- **Escritura única**: los asientos solo entran por `POST /internal/v1/postings` desde servicios de negocio; la API pública de `/api/v1/ledger/*` es de lectura (extractos/asientos propios).
- **Verificable**: `wallet` es una proyección reconciliable; job `balance_integrity_verification` y `ledger_balance_snapshots` comparan saldo derivado vs ledger (`L-ledger-architecture.md` §1).

## Consecuencias

### Positivas

- Ownership y blast radius claros: el schema de un servicio cae o se restaura con él.
- El aislamiento de datos es comprobable en CI, no una norma de estilo.
- Migraciones sin cadenas compartidas ni bloqueos cruzados entre servicios.
- El ledger es auditable, reproducible y resistente a alteración: base de la integridad financiera.
- Retención/clasificación por schema y por owner (facilita gobernanza de datos).

### Negativas

- Sin joins entre servicios: la composición obliga a API/BFF y a modelos de lectura propios (más código de orquestación).
- 13 usuarios, 13 cadenas de migraciones y grants a mantener; riesgo de grants mal configurados (mitigado con test de aislamiento).
- No hay transacciones ACID multi-servicio: la consistencia fuerte queda dentro del servicio; fuera es outbox + eventual (solo lectura/reporting, nunca dentro de un asiento).
- Restauraciones puntuales de un schema requieren runbook propio (backup físico compartido, lógico por servicio).

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **Base única con acceso libre a todas las tablas** | Anula la frontera de dominio: acoplamiento de datos, despliegues coordinados y riesgo de escrituras cruzadas sobre dinero. |
| **Un schema por dominio con varios servicios compartiéndolo** | Reintroduce el mismo problema en un escalón superior: quién migra, quién es dueño, qué pasa si dos servicios necesitan el mismo campo. |
| **Base de datos por servicio (instancia propia) desde Fase 1** | Coste operativo y de memoria desproporcionado para 3 servicios en compose; se reserva como evolución si el aislamiento a nivel de instancia se vuelve necesario. |
| **CQRS puro con eventos como única fuente de verdad y sin API síncrona** | La lectura de estado puntual (¿existe la orden?) vuelve imposible o costosa; se mantiene API síncrona + eventos (ADR-0007). |
| **Consultas federadas/vistas sobre schemas ajenos** | Es acceso cruzado con otro nombre: rompe el aislamiento y el versionado de datos. |

## Referencias

- `docs/phase0/00-decisions.md` §3 (schema propio, sin acceso cruzado), §5 (ledger como fuente de verdad).
- `docs/phase0/O-database-strategy.md` §1–§3 (ownership, tipos), §4 (migraciones), §6 (concurrencia), §9 (schemas por servicio).
- `docs/phase0/L-ledger-architecture.md` §1–§2 (principios y modelo del ledger).
- `docs/phase0/N-monorepo-structure.md` §8 (migraciones), §9 (reglas de aislamiento).
- `docs/phase0/G-security-architecture.md` §1.3 (acceso a datos entre servicios) y §10 (tampering de ledger).
- `docs/adr/ADR-0006-representacion-del-dinero.md`, `docs/adr/ADR-0007-eventos-con-outbox.md`, `docs/adr/ADR-0010-idempotencia-primero.md`.
