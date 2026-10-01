# O — Estrategia de Base de Datos

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)  
Proyecto: `MonedasAR` · Dominio: `[DOMAIN]` · Marca: `MonedasAR`

---

## 1. Separación de Datos por Dominio y Patrón de Acceso

| Capa | Tecnología | Justificación | Fase |
|---|---|---|---|
| **Transaccional (OLTP)** | PostgreSQL 17 (un schema por servicio) | ACID, consistencia fuerte, dinero, identidades | 1 |
| **Ledger (Fuente de verdad financiera)** | PostgreSQL 17 (schema `ledger`) | Append-only, double-entry, inmutable, auditoría | 2 |
| **Market Data (Time-series)** | PostgreSQL 17 + **TimescaleDB** (extensión) | Compresión nativa, hypertables, continuous aggregates | 3+ |
| **Analítica / OLAP** | **ClickHouse** | Columnar, compresión, scans rápidos, JOINs distribuidos | 7+ |
| **Logs / Observabilidad** | **Loki** (Grafana) | Indexado por labels, retención configurable, multi-tenant | 1 |
| **Objetos / Blobs** | **S3-compatible** (MinIO local, proveedor `REQUIERE PROVEEDOR` prod) | KYC docs, reportes, backups, snapshots | 1 |

> **Regla**: Un servicio = un schema PostgreSQL. **Ningún acceso cruzado a tablas**. Comunicación solo por API versionada + eventos.

---

## 2. Ownership de Schemas (Fase 1 Implementada)

| Servicio | Schema PostgreSQL | Owner (Equipo) | Tablas Principales (Fase 1) |
|---|---|---|---|
| `identity` | `identity` | Platform/Identity | `users`, `credentials`, `sessions`, `devices`, `mfa_factors`, `login_history`, `api_keys`, `roles`, `permissions`, `role_assignments` |
| `audit` | `audit` | Platform/Observability | `log_entries`, `event_subscriptions`, `integrity_chain` |
| `gateway` | *(sin schema propio — stateless)* | Platform/API | — |
| `notification` | `notification` | Platform/Comms | `templates`, `channels`, `deliveries`, `preferences` (Fase 2+) |
| `accounts` | `accounts` | Trading/Accounts | `trading_accounts`, `profiles`, `jurisdictions`, `account_limits` (Fase 2) |
| `wallet` | `wallet` | Trading/Wallet | `balances`, `balance_snapshots`, `currency_config` (Fase 2) |
| `ledger` | `ledger` | Trading/Ledger | `ledger_accounts`, `ledger_transactions`, `ledger_entries`, `ledger_idempotency_keys`, `ledger_balance_snapshots`, `outbox_events` (Fase 2) |
| `market-data` | `market_data` | Data/Market | `symbols`, `instrument_specs`, `trading_sessions`, `market_suspensions`, `market_holidays`, `outbox` (Fase 3), `ticks`, `candles` |
| `trading` | `trading` | Trading/OMS | `orders`, `positions`, `executions`, `margin_accounts` (Fase 4) |
| `risk` | `risk` | Risk/Engine | `limits`, `limit_breaches`, `circuit_breakers`, `kill_switches` (Fase 4) |
| `payments` | `payments` | Payments/Integrations | `deposits`, `withdrawals`, `psp_adapters`, `payment_methods` (Fase 6) |
| `kyc` | `kyc` | Compliance/KYC | `kyc_cases`, `documents`, `screenings`, `provider_responses` (Fase 6) |
| `admin` | `admin` | Platform/Admin | `feature_flags`, `system_config`, `audit_exports` (Fase 7) |

> **Convención**: Schema name = service name. Usuario DB por servicio (`identity_svc`, `ledger_svc`, etc.) con `GRANT USAGE, CREATE ON SCHEMA` + `DEFAULT PRIVILEGES`.

---

## 3. Tipos de Datos Canónicos

| Concepto | Tipo PostgreSQL | Tipo Python | Reglas |
|---|---|---|---|
| **ID expuesto** | `uuid` (UUIDv7 via `uuid_generate_v7()` o `gen_random_uuid()` v7-compat) | `uuid.UUID` | Nunca serial/bigint público |
| **Dinero (monto)** | `numeric(38,18)` | `decimal.Decimal` | **Nunca `float`/`real`/`double precision`** |
| **Moneda** | `char(3)` | `str` (ISO 4217) | `CHECK (currency ~ '^[A-Z]{3}$')` |
| **Timestamp canónico** | `timestamptz` (UTC) | `datetime` (tz-aware UTC) | `DEFAULT now()`; aplicación **siempre UTC** |
| **Enum versiónable** | **Tabla de referencia** (`*_types` con `code PK`, `description`, `is_active`, `sort_order`) | `str` / `Enum` | **No `CREATE TYPE ... AS ENUM`** para enums de negocio; migración = insert fila |
| **Enum técnico fijo** | `CREATE TYPE ... AS ENUM` | `Enum` | Solo para valores que **nunca cambian** (ej. `ledger_entry_direction` D/C) |
| **JSON extensible** | `jsonb` | `dict` / `pydantic.BaseModel` | `metadata`, `payload`, `response`; validado en app |
| **Hash/Checksum** | `char(64)` | `str` | SHA-256 hex (idempotency, integrity) |
| **Boolean flags** | `boolean` | `bool` | `is_active`, `is_control`, `published` |

### 3.1 Ejemplo: Enum Versiónable (Tabla de Referencia)

```sql
-- En lugar de CREATE TYPE account_status AS ENUM (...)
CREATE TABLE account_statuses (
    code        varchar(32) PRIMARY KEY,      -- 'active', 'suspended', 'closed', 'pending_kyc'
    description varchar(255) NOT NULL,
    is_active   boolean NOT NULL DEFAULT true,
    sort_order  int NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);
-- Migración para añadir estado: INSERT INTO account_statuses ...
-- App cachea en memoria con TTL; invalidación por event `ReferenceDataUpdated`
```

---

## 4. Migraciones: Estrategia Expand / Migrate / Contract

### 4.1 Principios

| Principio | Aplicación |
|---|---|
| **Backwards-compatible** | Migraciones nunca rompen versión N-1 de la API |
| **Expand primero** | Añadir columnas/tablas/índices **antes** de que el código los use |
| **Migrate datos** | Backfill en migración separada (no bloqueante si grande) |
| **Contract después** | Eliminar columnas/constraints **solo** tras confirmar que no se usan |
| **Sin hard delete datos financieros** | `ledger_entries`, `ledger_transactions`, `ledger_accounts` → **nunca** `DROP`/`DELETE` |
| **Soft delete solo donde aporte** | `deleted_at` + `WHERE deleted_at IS NULL` en vistas; índice parcial |

### 4.2 Flujo de Migración (Alembic)

```text
[Dev] alembic revision --autogenerate -m "add column X"
       ↓ revisar SQL generado (¡obligatorio!)
[CI]  alembic upgrade head (en test DB)
       ↓ tests pasan
[Staging] alembic upgrade head
       ↓ smoke tests
[Prod]  alembic upgrade head (ventana mantenimiento / blue-green)
```

### 4.3 Plantilla de Migración Segura

```python
# alembic/versions/xxxx_add_column_safe.py
"""Add nullable column, backfill, then NOT NULL"""

from alembic import op
import sqlalchemy as sa

revision = "xxxx"
down_revision = "yyyy"


def upgrade():
    # 1. EXPAND: añadir nullable
    op.add_column("users", sa.Column("timezone", sa.String(64), nullable=True))

    # 2. MIGRATE: backfill en batches (si tabla grande)
    op.execute("""
        UPDATE users SET timezone = 'UTC' 
        WHERE timezone IS NULL
    """)

    # 3. CONTRACT: NOT NULL + DEFAULT para futuros inserts
    op.alter_column("users", "timezone", nullable=False, server_default="UTC")


def downgrade():
    # Reverso seguro: solo si no hay datos dependientes
    op.drop_column("users", "timezone")
```

---

## 5. Índices por Patrón de Acceso (Anti-N+1)

### 5.1 Reglas Generales

- **Foreign Keys**: Índice automático en FK (PG no lo crea auto; `CREATE INDEX ON child(parent_id)`)
- **Composite indexes**: Orden = igualdad → rango → sort (`WHERE a=1 AND b>2 ORDER BY c`)
- **Partial indexes**: `WHERE published = false`, `WHERE deleted_at IS NULL`, `WHERE is_active`
- **Covering indexes**: `INCLUDE (col1, col2)` para index-only scans
- **Evitar N+1**: `SELECT * FROM orders JOIN executions ...` + `selectinload` / `joinedload` en SQLAlchemy

### 5.2 Índices Críticos por Servicio (Fase 1-2)

| Servicio | Tabla | Índice | Patrón |
|---|---|---|---|
| `identity` | `users` | `idx_users_email (email) WHERE deleted_at IS NULL` | Login, lookup único |
| `identity` | `sessions` | `idx_sessions_user_exp (user_id, expires_at DESC) WHERE revoked_at IS NULL` | Listar sesiones activas |
| `identity` | `sessions` | `idx_sessions_token (token_hash) WHERE revoked_at IS NULL` | Validar token (hash, no token plano) |
| `identity` | `api_keys` | `idx_api_keys_user (user_id) WHERE revoked_at IS NULL` | Listar keys de usuario |
| `audit` | `log_entries` | `idx_audit_corr (correlation_id)` | Trazabilidad request |
| `audit` | `log_entries` | `idx_audit_agg (aggregate_type, aggregate_id, created_at DESC)` | Historial entidad |
| `ledger` | `ledger_entries` | `idx_le_acct_time (account_id, created_at DESC)` | Extractos, running balance |
| `ledger` | `ledger_entries` | `idx_le_tx_pos (transaction_id, position)` | Reconstruir asiento |
| `ledger` | `ledger_transactions` | `idx_lt_corr (correlation_id)` | Rastreo externo |
| `ledger` | `outbox_events` | `idx_outbox_pub (published, created_at) WHERE NOT published` | Poller relay |
| `wallet` | `balances` | `idx_bal_user_curr (user_id, currency) WHERE deleted_at IS NULL` | Vista wallet |
| `accounts` | `trading_accounts` | `idx_ta_user (user_id) WHERE status='active'` | Cuentas de usuario |

---

## 6. Concurrencia y Bloqueos

### 6.1 Patrones por Caso de Uso

| Caso | Mecanismo | Ejemplo |
|---|---|---|
| **Actualización de saldo / asiento** | `SELECT ... FOR UPDATE` en `ledger_accounts` / `ledger_entries` | `POST /ledger/entries` dentro de tx |
| **Lectura consistente para decisión** | `SELECT ... FOR SHARE` (shared lock) | Verificar límite riesgo antes de orden |
| **Jobs singleton (cron, reconciliation)** | `pg_advisory_xact_lock(hash('job_name'))` | `balance_integrity_verification` |
| **Serialización retiros por cuenta** | `FOR UPDATE` en `wallet.balances` + `advisory_lock(account_id)` | `WithdrawalRequested` → `WithdrawalApproved` |
| **Idempotency key check-then-insert** | `INSERT ... ON CONFLICT (idempotency_key) DO UPDATE ...` | `ledger_idempotency_keys` |

### 6.2 Manejo de Deadlocks

```python
# Retry policy estándar para deadlock (SQLSTATE 40P01)
@retry(
    wait=wait_exponential_jitter(initial=0.05, max=0.5),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(DeadlockError),
    reraise=True,
)
async def execute_in_tx(session: AsyncSession, fn: Callable):
    async with session.begin():
        return await fn(session)
```

- **Orden de locks consistente**: Siempre `account_id` ascendente en multi-account tx
- **Timeout**: `lock_timeout = '2s'` en sesión; `idle_in_transaction_session_timeout = '30s'`

---

## 7. Escalado Futuro (Marcado PENDIENTE — No Implementar Fase 1-2)

| Estrategia | Aplicación | Trigger | Estado |
|---|---|---|---|
| **Read Replicas** | `identity`, `wallet`, `market-data`, `analytics` | CPU > 70% sostenido, latencia P99 > 200ms | `PENDIENTE` |
| **Partitioning Temporal** | `ledger_entries` (por mes), `market_data.ticks` (por día), `audit.log_entries` (por mes) | Tabla > 100GB o > 500M rows | `PENDIENTE` (pg_partman) |
| **Sharding por Tenant/Jurisdicción** | `ledger`, `wallet`, `accounts` | Multi-jurisdicción con data residency estricta | `PENDIENTE` (requiere routing layer) |
| **ClickHouse para Analytics** | `trading.executions`, `ledger_entries` (replicado), `market_data.candles` | Volumen > 1TB/año, queries analíticas > 30s | Fase 7+ |
| **TimescaleDB Continuous Aggregates** | `market_data.candles_1m`, `candles_1h` | Auto-materialización | Fase 3 |

> **Nota**: Sharding rompe transacciones distribuidas. Evaluar **solo** si requisito regulatorio (data residency) lo obliga. Preferir read replicas + partitioning.

---

## 8. Backup / Restore: RPO / RTO

| Métrica | Valor Propuesto (DECIDIR) | Justificación |
|---|---|---|
| **RPO (Recovery Point Objective)** | **5 minutos** (WAL streaming + `pg_receivewal`) | Pérdida máxima 5 min de transacciones |
| **RTO (Recovery Time Objective)** | **30 minutos** (restore + replay WAL) | Incluye verificación de integridad ledger |
| **Full Backup** | Diario 02:00 UTC (`pg_basebackup` + compresión) | Base para PITR |
| **WAL Archiving** | Continuo a S3 (`archive_command`) | Point-in-time recovery |
| **Prueba de Restauración** | **Mensual** (obligatoria) en staging; documento `restore_report_YYYY-MM.md` | Validar RTO real |
| **Retención Backups** | Diarios 30 días, Semanales 12 semanas, Mensuales 7 años (regulatorio) | Cumplimiento financiero |

### 8.1 Procedimiento de Restore (Resumen)

```bash
# 1. Detener servicios writers
# 2. Restaurar base desde pg_basebackup más reciente
# 3. Configurar recovery.signal + restore_command (WAL desde S3)
# 4. Iniciar PostgreSQL → replay hasta target_time
# 5. Verificar: ledger_balance_snapshots.matched = true para todas las cuentas
# 6. Ejecutar sanity checks (invariantes §8 doc L)
# 7. Levantar servicios
```

---

## 9. Resumen de Schemas por Servicio (Fase 1 Real, Resto Previsto)

| Servicio | Fase | Estado | Tablas Previstas (Principales) |
|---|---|---|---|
| `gateway` | 1 | `IMPLEMENTADO` | *(stateless — sin schema)* |
| `identity` | 1 | `IMPLEMENTADO` | `users`, `credentials`, `sessions`, `devices`, `mfa_factors`, `login_history`, `api_keys`, `roles`, `permissions`, `role_assignments`, `email_verifications`, `password_resets` |
| `audit` | 1 | `IMPLEMENTADO` | `log_entries`, `event_subscriptions`, `integrity_chain`, `export_jobs` |
| `notification` | 2+ | `PENDIENTE` | `templates`, `channels`, `deliveries`, `preferences`, `webhook_endpoints` |
| `accounts` | 2 | `PENDIENTE` | `trading_accounts`, `profiles`, `jurisdictions`, `account_limits`, `account_statuses` (ref), `kyc_links` |
| `wallet` | 2 | `PENDIENTE` | `balances`, `balance_snapshots`, `currency_config`, `conversion_rates` |
| `ledger` | 2 | `PENDIENTE` | `ledger_accounts`, `ledger_transactions`, `ledger_entries`, `ledger_idempotency_keys`, `ledger_balance_snapshots`, `outbox_events` |
| `market-data` | 3 | `IMPLEMENTADO` (parcial BUILD-027: `ticks`, `candles`; BUILD-028: `symbols`, `instrument_specs`, `trading_sessions`, `market_suspensions`, `market_holidays`, `outbox` con seed demo; restan `provider_status` + hypertables/retención = DECIDIR) | `symbols`, `ticks`, `candles`, `instrument_specs`, `trading_sessions`, `market_suspensions`, `market_holidays`, `outbox`, `provider_status` |
| `trading` | 4 | `PENDIENTE` | `orders`, `positions`, `executions`, `margin_accounts`, `order_legs`, `position_history` |
| `risk` | 4 | `PENDIENTE` | `limits`, `limit_breaches`, `circuit_breakers`, `kill_switches`, `risk_metrics_snapshots` |
| `payments` | 6 | `PENDIENTE` | `deposits`, `withdrawals`, `psp_adapters`, `payment_methods`, `psp_webhooks`, `fee_schedules` |
| `kyc` | 6 | `PENDIENTE` | `kyc_cases`, `documents`, `screenings`, `provider_responses`, `risk_scores`, `aml_alerts` |
| `admin` | 7 | `PENDIENTE` | `feature_flags`, `system_config`, `audit_exports`, `admin_users`, `role_definitions` |

---

## 10. Decisiones Pendientes (Marcadas)

| Tema | Estado | Detalle |
|---|---|---|
| Proveedor S3 producción | `REQUIERE PROVEEDOR` | AWS S3 / GCS / Azure Blob / MinIO on-prem |
| Vault/KMS producción | `REQUIERE PROVEEDOR` | HashiCorp Vault / AWS KMS / GCP KMS / Azure Key Vault |
| ClickHouse deployment (managed vs self-hosted) | `DECIDIR` Fase 6 | Coste vs. control |
| TimescaleDB: managed (Timescale Cloud) vs self-hosted | `DECIDIR` Fase 3 | |
| RPO/RTO exactos validados con negocio | `DECIDIR` | Reunión con CRO/Compliance |
| Column-level encryption para PII en `identity` | `DECIDIR` | `pgcrypto` vs application-level |
| Connection pooling: PgBouncer (transaction) vs session | `DECIDIR` | Transaction pooling rompe advisory locks; evaluar |

---

*Fin del documento O-database-strategy.md*