# ADR-0014 — Migraciones Alembic backwards-compatible y despliegue expand/migrate/contract

| Campo | Valor |
|---|---|
| **Estado** | Aceptada |
| **Fecha** | 2026-09-27 |
| **Alcance** | todos los `services/*` con schema PostgreSQL propio (Fase 1: `identity`, `audit`; fases siguientes) |
| **Fuente canónica** | `docs/phase0/O-database-strategy.md` §4 · `docs/phase0/N-monorepo-structure.md` §8 |

## Contexto

- Cada servicio tiene su schema PostgreSQL propio, sin acceso cruzado a tablas (`00-decisions.md` §3) y con su propia cadena de revisiones Alembic (`N-monorepo-structure.md` §8), por lo que las migraciones son la única forma de evolucionar el esquema.
- REQ-089 exige estrategia expand-migrate-contract para cambios incompatibles, y el riesgo R-024 clasifica como crítica la migración destructiva (`DROP`/`RENAME`/backfill masivo) sobre datos financieros o PII sin reversión.
- `N-monorepo-structure.md` regla 7: la migración se mergea **antes o junto con** el código que la usa, en modo compatible, para permitir rollback sin pérdida de datos.
- `L-ledger-architecture.md` §9 fija que los asientos financieros son permanentes: ninguna migración puede borrarlos.
- El flujo actual (`O-database-strategy.md` §4.2) es dev → `alembic upgrade head` en CI sobre BD de test → staging → producción con ventana o blue-green; no hay herramienta comercial de despliegue zero-downtime evaluada.

## Decisión

1. **Backwards-compatible por defecto**: ninguna migración rompe a la versión N-1 de la aplicación ni a los servicios consumidores de API/eventos. La aplicación nueva debe funcionar con el esquema anterior y con el nuevo durante la ventana de despliegue.
2. **Tres fases explícitas, en releases separados cuando aplique**:
   - **EXPAND**: añadir columnas/tablas/índices/enum de forma compatible (columna nullable o con `server_default`, tablas nuevas, índices `CONCURRENTLY` cuando la tabla esté en uso).
   - **MIGRATE**: backfill de datos en lotes acotados (`LIMIT` + reintentos, sin transacciones de horas), de modo que la escritura siga disponible; el backfill es idempotente y re-ejecutable.
   - **CONTRACT**: endurecer (`NOT NULL`, constraints de dominio) o eliminar columnas/tablas **solo** cuando ninguna versión en producción lee/escribe lo antiguo y tras una ventana de observación.
3. **Sin hard delete de datos financieros**: `ledger_entries`, `ledger_transactions` y `ledger_accounts` no admiten `DROP` ni `DELETE` por migración (ver ADR-0011). La corrección de datos del ledger es por transacción de reversión, nunca por `UPDATE` masivo desde una migración. Lo mismo aplica a `audit.log_entries`.
4. **PII y datos de usuario**: soft delete (`deleted_at` + índice parcial) en lugar de `DROP` de filas; la eliminación real de PII se hace por proceso de retención documentado (con `O-database-strategy.md` y owner/steward), no como efecto colateral de una migración de esquema.
5. **Proceso obligatorio por migración**: `alembic revision --autogenerate` con **revisión humana del SQL generado** (el autogenerado propone `DROP`/recrear índices si hay deriva); `alembic upgrade head` + tests en CI sobre BD de test; `alembic downgrade -1` probado o `downgrade` declarado como no soportado **con justificación explícita** en la revisión; en staging con smoke tests; en producción con backup/PITR verificado, dry-run sobre copia, ventana, plan de rollback y responsable nombrados (R-024).
6. **Idempotencia**: toda migración puede re-ejecutarse sin error (guardas `IF NOT EXISTS`, verificación previa), porque los reintentos en entornos con múltiples réplicas o migraciones a medias son habituales.
7. **Los contratos de datos no se rompen en el mismo release**: cambios de columna usados por API/eventos requieren primero expand + código dual-write/dual-read, luego migración de datos, y solo después contract. Aplica también a `platform-contracts` (OpenAPI, schemas de eventos, ADR-0016).
8. **CI como gate**: el job de migraciones (upgrade + downgrade + tests) es bloqueante en toda PR que toque `alembic/versions/` o modelos SQLAlchemy; se añade una regla que prohíbe operaciones destructivas sobre tablas financieras en revisiones.

## Consecuencias

### Positivas

- Despliegues sin ventana obligatoria en la mayoría de cambios y rollback de aplicación sin pérdida de datos (la BD soporta N y N-1).
- Datos financieros e históricos preservados: auditoría y reconstrucción de saldos intactas (consistente con ADR-0011).
- Migraciones re-ejecutables y revisadas: menos incidentes por SQL autogenerado sorpresa (R-024 mitigado).
- El patrón es el mismo en los 13 schemas del monorepo: runbook único y revisables por cualquier ingeniero.

### Negativas

- Esquemas con columnas duplicadas o intermedias durante varias releases: "deuda de contract" que hay que planificar retirar (inventario de fases pendientes por servicio).
- Tres fases multiplican el número de PRs/migraciones respecto a un cambio directo.
- Backfills en lotes alargan la transición de datos y requieren monitorización (progreso, bloqueos, `lock` de tablas).
- `CONCURRENTLY`/`CREATE INDEX` en tablas grandes exige cuidado con autocommit y con el uso de BD en prod (no siempre aplicable en CI donde no importa).
- `downgrade` no soportado en algunos cambios (p. ej. pérdida de columnas) deja el rollback limitado a rollback de aplicación sobre el esquema nuevo, no a revertir la BD.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Migración directa destructiva en la release de corte (`DROP`+recrear) | R-024: pérdida de datos sin reversión; impide rollback; prohibida para ledger/audit. |
| `create_all`/auto-sync del ORM al arrancar la app | Sin historial versionado, sin control de cambios, sin downgrade y con riesgo de alterar producción al desplegar; inaceptable para dinero. |
| SQL manual sin Alembic por servicio | Pierde cadena de revisiones, autogenerado revisable, CI reproducible y consistencia entre 13 schemas; ya elegido Alembic en `M-tech-stack.md` §5. |
| Herramienta comercial de despliegue sin caída (zero-downtime, `REQUIERE PROVEEDOR`) | Evaluable solo con evidencia de necesidad; el patrón expand/migrate/contract cubre el requisito con herramientas ya presentes. |
| Ventana de mantenimiento con parada total para migrar | Aceptada solo como excepción puntual (riesgo alto, tamaño de backfill), no como procedimiento normal: degrada disponibilidad sin necesidad. |

## Referencias

- `docs/phase0/O-database-strategy.md` §4 (expand/migrate/contract, flujo y plantilla)
- `docs/phase0/N-monorepo-structure.md` §8 (cadenas Alembic por servicio, regla 7 de compatibilidad)
- `docs/phase0/B-requirements-matrix.md` REQ-089
- `docs/phase0/V-risk-register.md` R-024 (migraciones destructivas)
- `docs/phase0/L-ledger-architecture.md` §9 (retención, sin DELETE en el ledger)
- `docs/phase0/S-mvp-scope.md` §2.2 (`alembic upgrade head` / `downgrade -1`)
- ADR-0011 (inmutabilidad del ledger), ADR-0016 (compatibilidad de contratos de eventos)
