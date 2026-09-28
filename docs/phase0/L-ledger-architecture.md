# L — Arquitectura del Ledger (Fuente de Verdad Financiera)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)  
Proyecto: `MonedasAR` · Dominio: `[DOMAIN]` · Marca: `MonedasAR`

---

## 1. Principios Inmutables

| Principio | Descripción | Implementación |
|---|---|---|
| **Double-Entry** | Cada movimiento afecta ≥2 cuentas; suma débitos = suma créditos por transacción | `CHECK` en `ledger_entries` + validación en aplicación |
| **Append-Only** | Nunca `UPDATE`/`DELETE` en `ledger_entries`; correcciones solo vía transacción de reversión | `reverses_entry_id` / `reversal_of` FK a sí mismo |
| **Inmutable** | Asientos escritos una sola vez; hash encadenado opcional para tamper-evidence | `created_at` + `entry_hash` (SHA-256 de fila anterior + actual) |
| **Idempotente** | Reenvío de mismo `Idempotency-Key` + hash de payload produce mismo resultado | Tabla `ledger_idempotency_keys` con respuesta almacenada |
| **Auditable** | Trazabilidad completa: `correlation_id`, `causation_id`, `occurred_at`, metadata | Índices + outbox event `LedgerPosted` |
| **Reconciliable** | Balances derivados verificables contra ledger; snapshots diarios | Job `balance_integrity_verification` + `ledger_balance_snapshots` |
| **Transaccional** | Asiento + outbox en misma transacción ACID | `INSERT` en `ledger_entries` + `outbox_events` atómico |

---

## 2. Modelo de Datos Propuesto

### 2.1 Esquema ER (Mermaid)

```mermaid
erDiagram
    LEDGER_ACCOUNTS ||--o{ LEDGER_ENTRIES : "has"
    LEDGER_TRANSACTIONS ||--o{ LEDGER_ENTRIES : "contains"
    LEDGER_TRANSACTIONS }|--o{ LEDGER_TRANSACTIONS : "reverses (self-ref)"
    LEDGER_ENTRIES }|--o{ LEDGER_ENTRIES : "reverses_entry (self-ref)"
    LEDGER_ACCOUNTS {
        uuid id PK
        varchar code UK "ej. 1000.CASH.USD"
        varchar name
        varchar type "asset|liability|equity|revenue|expense"
        char(3) currency ISO 4217
        uuid owner_id "user_id o tenant_id"
        varchar owner_type "user|tenant|system"
        boolean is_control "cuenta de control/sistema"
        timestampz created_at
        timestampz closed_at NULL
    }
    LEDGER_TRANSACTIONS {
        uuid id PK "UUIDv7"
        varchar type "deposit|withdrawal|transfer|conversion|fee|swap|pnl|margin_funding|reversal|adjustment"
        uuid correlation_id "trace externo"
        uuid causation_id "evento origen"
        timestampz occurred_at "UTC"
        jsonb metadata "extensible"
        uuid reverses_tx_id FK NULL "transacción que revierte"
        timestampz created_at
    }
    LEDGER_ENTRIES {
        uuid id PK "UUIDv7"
        uuid transaction_id FK
        uuid account_id FK
        char(1) direction "D|C" CHECK (direction IN ('D','C'))
        numeric(38,18) amount "siempre positivo"
        char(3) currency ISO 4217
        numeric(38,18) balance_after "opcional, materializado"
        uuid reverses_entry_id FK NULL "entrada que revierte"
        int position "orden dentro de transacción"
        timestampz created_at
    }
    LEDGER_IDEMPOTENCY_KEYS {
        varchar idempotency_key PK
        varchar request_hash "SHA-256(payload canonizado)"
        uuid transaction_id "resultado"
        jsonb response "respuesta almacenada"
        timestampz expires_at
        timestampz created_at
    }
    LEDGER_BALANCE_SNAPSHOTS {
        uuid id PK
        uuid account_id FK
        date snapshot_date "fecha cierre"
        numeric(38,18) balance "saldo verificado"
        numeric(38,18) ledger_balance "saldo calculado del ledger"
        boolean matched "integrity check"
        timestampz verified_at
    }
    OUTBOX_EVENTS {
        uuid id PK
        varchar aggregate_type "LedgerTransaction"
        uuid aggregate_id
        varchar event_type "LedgerPosted"
        int schema_version
        jsonb payload
        boolean published
        timestampz created_at
        timestampz published_at NULL
    }
```

### 2.2 Definiciones SQL (PostgreSQL 17)

```sql
-- Esquema: ledger (schema propio del servicio ledger)

CREATE TYPE ledger_account_type AS ENUM ('asset','liability','equity','revenue','expense');
CREATE TYPE ledger_entry_direction AS ENUM ('D','C');
CREATE TYPE ledger_tx_type AS ENUM (
    'deposit','withdrawal','transfer','conversion','fee',
    'swap','pnl','margin_funding','reversal','adjustment'
);

CREATE TABLE ledger_accounts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(), -- UUIDv7 via extension
    code            varchar(64) NOT NULL UNIQUE,                -- ej. '1000.CASH.USD'
    name            varchar(255) NOT NULL,
    type            ledger_account_type NOT NULL,
    currency        char(3) NOT NULL,                           -- ISO 4217
    owner_id        uuid NOT NULL,                              -- user_id | tenant_id | system
    owner_type      varchar(16) NOT NULL CHECK (owner_type IN ('user','tenant','system')),
    is_control      boolean NOT NULL DEFAULT false,             -- cuentas de sistema (fees, PnL, etc.)
    created_at      timestamptz NOT NULL DEFAULT now(),
    closed_at       timestamptz NULL,
    CONSTRAINT chk_code_format CHECK (code ~ '^[0-9]{4}\.[A-Z0-9_]+\.[A-Z]{3}$')
);

CREATE TABLE ledger_transactions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type            ledger_tx_type NOT NULL,
    correlation_id  uuid NOT NULL,
    causation_id    uuid NULL,
    occurred_at     timestamptz NOT NULL,
    metadata        jsonb NOT NULL DEFAULT '{}',
    reverses_tx_id  uuid NULL REFERENCES ledger_transactions(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ledger_entries (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id      uuid NOT NULL REFERENCES ledger_transactions(id) ON DELETE RESTRICT,
    account_id          uuid NOT NULL REFERENCES ledger_accounts(id) ON DELETE RESTRICT,
    direction           ledger_entry_direction NOT NULL,
    amount              numeric(38,18) NOT NULL CHECK (amount > 0),
    currency            char(3) NOT NULL,
    balance_after       numeric(38,18) NULL,                      -- materializado opcional
    reverses_entry_id   uuid NULL REFERENCES ledger_entries(id),  -- para reversiones granulares
    position            int NOT NULL,                             -- orden determinístico
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_tx_position UNIQUE (transaction_id, position)
);

-- Regla de oro: suma débitos = suma créditos POR TRANSACCIÓN
-- Se valida en aplicación ANTES del INSERT; como defensa en profundidad:
CREATE OR REPLACE FUNCTION ledger_assert_balanced(tx_id uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE diff numeric;
BEGIN
    SELECT SUM(CASE WHEN direction = 'D' THEN amount ELSE -amount END)
      INTO diff FROM ledger_entries WHERE transaction_id = tx_id;
    IF diff IS NOT NULL AND diff <> 0 THEN
        RAISE EXCEPTION 'Transaction % not balanced: net %', tx_id, diff;
    END IF;
END $$;

-- Trigger AFTER INSERT en ledger_entries para validar al cerrar transacción
-- (la app llama a ledger_assert_balanced(tx_id) antes de COMMIT)

CREATE TABLE ledger_idempotency_keys (
    idempotency_key   varchar(128) PRIMARY KEY,
    request_hash      char(64) NOT NULL,                          -- SHA-256 hex
    transaction_id    uuid NOT NULL REFERENCES ledger_transactions(id),
    response          jsonb NOT NULL,
    expires_at        timestamptz NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_ledger_idempotency_expires ON ledger_idempotency_keys(expires_at);

CREATE TABLE ledger_balance_snapshots (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      uuid NOT NULL REFERENCES ledger_accounts(id),
    snapshot_date   date NOT NULL,
    balance         numeric(38,18) NOT NULL,          -- saldo en wallet/cuenta (proyección)
    ledger_balance  numeric(38,18) NOT NULL,          -- Σ entries hasta snapshot_date
    matched         boolean NOT NULL,
    verified_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (account_id, snapshot_date)
);

CREATE INDEX idx_ledger_balance_snapshots_date ON ledger_balance_snapshots(snapshot_date);

-- Outbox transaccional (misma tx que ledger_entries)
CREATE TABLE outbox_events (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type  varchar(64) NOT NULL,
    aggregate_id    uuid NOT NULL,
    event_type      varchar(128) NOT NULL,
    schema_version  int NOT NULL DEFAULT 1,
    payload         jsonb NOT NULL,
    published       boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    published_at    timestamptz NULL
);

CREATE INDEX idx_outbox_unpublished ON outbox_events(published, created_at) WHERE NOT published;
CREATE INDEX idx_outbox_aggregate ON outbox_events(aggregate_type, aggregate_id);
```

### 2.3 Índices Críticos por Patrón de Acceso

| Tabla | Índice | Justificación |
|---|---|---|
| `ledger_entries` | `(account_id, created_at DESC)` | Extractos de cuenta, balances running |
| `ledger_entries` | `(account_id, id)` | Paginación estable por posición |
| `ledger_entries` | `(transaction_id, position)` | Reconstrucción de asiento completo |
| `ledger_transactions` | `(correlation_id)` | Rastreo por request externo |
| `ledger_transactions` | `(occurred_at)` | Ventanas temporales, reportes |
| `ledger_accounts` | `(owner_id, owner_type, currency)` | Listar cuentas de un usuario |
| `outbox_events` | `(published, created_at) WHERE NOT published` | Poller eficiente |
| `ledger_idempotency_keys` | `(expires_at)` | Limpieza TTL |

---

## 3. Regla de Inmutabilidad y Correcciones

| Operación | Permitida | Mecanismo |
|---|---|---|
| `INSERT` en `ledger_entries` | ✅ | Única forma de crear asientos |
| `UPDATE` en `ledger_entries` | ❌ | Prohibido por política y `REVOKE UPDATE` |
| `DELETE` en `ledger_entries` | ❌ | Prohibido; `ON DELETE RESTRICT` en FKs |
| Corrección de error | ✅ | Transacción tipo `reversal` con `reverses_tx_id` |
| Reversión granular | ✅ | `ledger_entries.reverses_entry_id` apunta a entry original |
| Ajuste contable | ✅ | Transacción tipo `adjustment` con metadata justificativa |

**Ejemplo reversión:**
```sql
-- Transacción original: tx_123 (deposit)
-- Reversión: nueva transacción tx_456 type='reversal', reverses_tx_id=tx_123
-- Entries de tx_456: direction invertida, reverses_entry_id apunta a cada entry de tx_123
```

---

## 4. Derivación de Balances y Verificación de Integridad

### 4.1 Proyección Materializada (Wallet)

```sql
-- Vista para balance actual por cuenta (no materializada, calculada on-demand)
CREATE VIEW ledger_account_balances AS
SELECT
    la.id AS account_id,
    la.code,
    la.currency,
    COALESCE(SUM(CASE WHEN le.direction = 'D' THEN le.amount ELSE -le.amount END), 0) AS balance
FROM ledger_accounts la
LEFT JOIN ledger_entries le ON le.account_id = la.id
GROUP BY la.id, la.code, la.currency;
```

### 4.2 Job: Balance Integrity Verification (Diario)

```python
# Pseudocódigo del job programado (Airflow/Temporal/cron)
async def verify_balance_integrity(date: date):
    for account in ledger_accounts_active():
        ledger_bal = compute_ledger_balance(account.id, date)  # Σ entries ≤ date
        wallet_bal = get_wallet_projection(account.id)  # tabla wallet.balances
        matched = ledger_bal == wallet_bal
        await upsert_snapshot(account.id, date, wallet_bal, ledger_bal, matched)
        if not matched:
            emit_alert(f"Balance mismatch account={account.id} ledger={ledger_bal} wallet={wallet_bal}")
```

### 4.3 Daily Closing & Snapshots

| Acción | Frecuencia | Detalle |
|---|---|---|
| `ledger_balance_snapshots` insert | Diario (00:05 UTC) | Una fila por cuenta activa |
| Reconciliación contra `wallet` | Diario | Alerta si `matched = false` |
| Cierre contable mensual | Mensual | Reporte PDF/CSV firmado, inmutable en S3 |
| Verificación hash chain (opcional) | Semanal | Detecta manipulación histórica |

---

## 5. Patrón de Publicación: Transactional Outbox

```sql
-- En la MISMA transacción que INSERT ledger_entries:
INSERT INTO outbox_events (aggregate_type, aggregate_id, event_type, schema_version, payload)
VALUES (
    'LedgerTransaction',
    $tx_id,
    'LedgerPosted',
    1,
    jsonb_build_object(
        'transaction_id', $tx_id,
        'type', $tx_type,
        'correlation_id', $correlation_id,
        'occurred_at', $occurred_at,
        'entries', (
            SELECT jsonb_agg(jsonb_build_object(
                'account_id', account_id,
                'direction', direction,
                'amount', amount,
                'currency', currency
            ) ORDER BY position)
            FROM ledger_entries WHERE transaction_id = $tx_id
        )
    )
);
```

**Poller/Relay:** Lee `outbox_events WHERE NOT published ORDER BY created_at LIMIT 100`, publica a Redpanda, marca `published=true, published_at=now()` en misma transacción.

---

## 6. Idempotencia en Postings

```python
async def post_ledger_transaction(cmd: PostLedgerCommand, idempotency_key: str) -> LedgerTransaction:
    request_hash = sha256(canonical_json(cmd.model_dump()))
    
    # 1. Verificar clave existente
    existing = await db.fetchrow(
        "SELECT transaction_id, response FROM ledger_idempotency_keys WHERE idempotency_key = $1",
        idempotency_key
    )
    if existing:
        if existing['request_hash'] != request_hash:
            raise IdempotencyConflict("Same key, different payload")
        return existing['response']  # Respuesta cacheada
    
    # 2. Ejecutar transacción ledger (ACID)
    async with db.transaction():
        tx = await create_ledger_transaction(cmd)
        # ... inserts entries ...
        await db.execute(
            "INSERT INTO ledger_idempotency_keys (idempotency_key, request_hash, transaction_id, response, expires_at) VALUES ($1,$2,$3,$4,$5)",
            idempotency_key, request_hash, tx.id, tx.model_dump_json(), now() + interval '7 days'
        )
    return tx
```

---

## 7. Mapeo de Flujos a Cuentas (Ejemplos de Asientos)

### 7.1 Plan de Cuentas Base (Sugerido)

| Código | Nombre | Tipo | Moneda | Propósito |
|---|---|---|---|---|
| `1000.CASH.USD` | Efectivo USD | asset | USD | Fondos de clientes segregados |
| `1000.CASH.EUR` | Efectivo EUR | asset | EUR | Fondos de clientes segregados |
| `1200.RECEIVABLE.PSP` | Por cobrar PSP | asset | USD | Depósitos en tránsito |
| `2000.PAYABLE.CLIENT` | Por pagar clientes | liability | USD | Balances de clientes (wallet) |
| `2100.PAYABLE.PSP` | Por pagar PSP | liability | USD | Retiros pendientes |
| `4000.REVENUE.FEE` | Ingresos comisiones | revenue | USD | Fees trading |
| `4100.REVENUE.SWAP` | Ingresos swap | revenue | USD | Financiación overnight |
| `5000.EXPENSE.PSP` | Gastos PSP | expense | USD | Costos procesamiento |
| `3000.EQUITY.PNL` | PnL realizado | equity | USD | Resultado neto clientes |
| `1100.MARGIN.USD` | Margen depositado | asset | USD | Colateral posiciones |

> **Nota**: Cuentas `2000.PAYABLE.CLIENT` son **una por usuario+moneda** (ej. `2000.PAYABLE.CLIENT.USD.u_abc123`). `owner_id` = `user_id`, `is_control=false`.

### 7.2 Depósito (Cliente → Plataforma)

```text
Transacción: type='deposit', correlation_id=dep_abc123
┌─────────────────────────────────────────────────────────────┐
│ DEBIT  1200.RECEIVABLE.PSP.USD      +1,000.00  (fondos en tránsito PSP) │
│ CREDIT 2000.PAYABLE.CLIENT.USD.u1   +1,000.00  (balance cliente)       │
└─────────────────────────────────────────────────────────────┘
-- Al confirmar PSP:
Transacción: type='deposit', correlation_id=dep_abc123 (misma correlation)
┌─────────────────────────────────────────────────────────────┐
│ DEBIT  1000.CASH.USD              +1,000.00  (efectivo real)          │
│ CREDIT 1200.RECEIVABLE.PSP.USD    -1,000.00  (liquidar receivable)    │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 Retiro (Plataforma → Cliente)

```text
Transacción: type='withdrawal', correlation_id=wth_xyz789
┌─────────────────────────────────────────────────────────────┐
│ DEBIT  2000.PAYABLE.CLIENT.USD.u1   -500.00   (reducir balance) │
│ CREDIT 2100.PAYABLE.PSP.USD         +500.00   (pendiente PSP)   │
└─────────────────────────────────────────────────────────────┘
-- Al ejecutar PSP:
Transacción: type='withdrawal', correlation_id=wth_xyz789
┌─────────────────────────────────────────────────────────────┐
│ DEBIT  2100.PAYABLE.PSP.USD         -500.00   (liquidar payable)  │
│ CREDIT 1000.CASH.USD              -500.00   (salida efectivo)     │
└─────────────────────────────────────────────────────────────┘
```

### 7.4 Transferencia Interna (Usuario A → Usuario B, misma moneda)

```text
Transacción: type='transfer', correlation_id=trf_456
┌─────────────────────────────────────────────────────────────┐
│ DEBIT  2000.PAYABLE.CLIENT.USD.uA   -200.00   (origen)        │
│ CREDIT 2000.PAYABLE.CLIENT.USD.uB   +200.00   (destino)       │
└─────────────────────────────────────────────────────────────┘
```

### 7.5 Conversión (FX) — *Pendiente de implementación completa*

```text
Transacción: type='conversion', correlation_id=fx_789
┌─────────────────────────────────────────────────────────────┐
│ DEBIT  2000.PAYABLE.CLIENT.USD.u1   -1,000.00  (origen)       │
│ CREDIT 2000.PAYABLE.CLIENT.EUR.u1   +920.00   (destino, rate 0.92)│
│ DEBIT  4000.REVENUE.FEE.USD         +8.00       (spread/comisión) │
│ CREDIT 2000.PAYABLE.CLIENT.USD.u1   -8.00       (fee al cliente)   │
└─────────────────────────────────────────────────────────────┘
```

### 7.6 Comisión (Fee) — Trading

```text
Transacción: type='fee', correlation_id=ord_111
┌─────────────────────────────────────────────────────────────┐
│ DEBIT  2000.PAYABLE.CLIENT.USD.u1   -5.00    (cargo al cliente)│
│ CREDIT 4000.REVENUE.FEE.USD         +5.00    (ingreso plataforma)│
└─────────────────────────────────────────────────────────────┘
```

### 7.7 Swap (Financiación Overnight)

```text
Transacción: type='swap', correlation_id=pos_222
┌─────────────────────────────────────────────────────────────┐
│ DEBIT  2000.PAYABLE.CLIENT.USD.u1   -12.50   (cargo swap)    │
│ CREDIT 4100.REVENUE.SWAP.USD        +12.50   (ingreso swap)  │
└─────────────────────────────────────────────────────────────┘
```

### 7.8 PnL Realizado (Cierre Posición)

```text
Transacción: type='pnl', correlation_id=pos_222
┌─────────────────────────────────────────────────────────────┐
│ DEBIT  2000.PAYABLE.CLIENT.USD.u1   -250.00  (pérdida cliente)│
│ CREDIT 3000.EQUITY.PNL.USD          +250.00  (equity PnL)    │
└─────────────────────────────────────────────────────────────┘
-- Si ganancia: signs invertidos (DEBIT equity, CREDIT client)
```

### 7.9 Financiación de Margen (Margin Funding)

```text
Transacción: type='margin_funding', correlation_id=pos_333
┌─────────────────────────────────────────────────────────────┐
│ DEBIT  2000.PAYABLE.CLIENT.USD.u1   -1,000.00  (mover a margen)│
│ CREDIT 1100.MARGIN.USD              +1,000.00  (colateral)    │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Invariantes Financieros Verificables (Tests Obligatorios)

| # | Invariante | Descripción | Test Sugerido |
|---|---|---|---|
| 1 | **Suma débitos = suma créditos** | Por cada `ledger_transactions.id` | `assert sum(D) == sum(C) per tx` |
| 2 | **Balances no negativos (activos)** | Cuentas `asset` ≥ 0 siempre | `assert balance >= 0 for type=asset` |
| 3 | **Balances no positivos (pasivos/equity)** | Cuentas `liability`/`equity` ≤ 0 (convención) | `assert balance <= 0 for type in (liability,equity)` |
| 4 | **Conservación de moneda** | No mezcla de monedas en una transacción sin conversión explícita | `assert distinct(currency) == 1 OR type='conversion'` |
| 5 | **Idempotencia** | Mismo `idempotency_key` + hash → misma `transaction_id` | Replay 100x mismo key → 1 tx |
| 6 | **Reversión simétrica** | `reversal` invierte signos y referencias `reverses_*` | `original + reversal == net zero` |
| 7 | **Outbox atómico** | Cada `ledger_transactions` commit ⇒ 1 `outbox_events` `LedgerPosted` | `count(tx) == count(outbox LedgerPosted)` |
| 8 | **Integridad snapshots** | `ledger_balance_snapshots.ledger_balance == Σ entries ≤ date` | Job diario verifica `matched=true` |
| 9 | **Orden determinístico** | `position` único por transacción, sin gaps | `assert positions == 1..N` |
| 10 | **Referencial integrity** | `account_id` existe, `currency` coincide con cuenta | FK + `CHECK entries.currency = accounts.currency` |

> **Cobertura mínima Fase 2**: Tests 1–8 automatizados en CI. Tests 9–10 en migración/schema.

---

## 9. Consideraciones de Retención, Auditoría y Gobernanza (DAMA-DMBOK Breve)

| Dimensión | Decisión |
|---|---|
| **Owner/Steward** | `ledger` service team (data owner); CFO/Compliance (data steward) |
| **Clasificación** | `CONFIDENTIAL` (datos financieros de clientes); `INTERNAL` (cuentas de control sistema) |
| **Schema/Contrato** | Versionado en `docs/adr/ADR-0005` + `ledger_accounts.code` como clave natural estable |
| **Calidad** | Validaciones: `amount>0`, `direction∈{D,C}`, `balance_after` coherente, `CHECK` balanced |
| **Lineage** | `ledger_transactions.causation_id` → evento origen; `correlation_id` → request externo; `reverses_tx_id` → cadena de corrección |
| **Consumidores** | `wallet` (proyección), `risk` (límites), `audit` (log), `reporting` (analytics), `tax/regulatory` |
| **Retención** | **Asientos financieros: PERMANENTE (no hard delete)**. `ledger_idempotency_keys`: TTL 7 días. `outbox_events`: TTL 30 días tras published. Snapshots: 7 años mínimo (regulatorio). |
| **Permisos** | `ledger` service: R/W; `wallet`/`risk`: READ only via API; `audit`: READ via events; `admin`: READ con approval |
| **Cifrado** | En reposo: PostgreSQL TDE / volume encryption. En tránsito: TLS 1.3. Campos sensibles (metadata PII): `pgcrypto` column-level si aplica. |
| **Auditoría** | `audit` service consume `LedgerPosted` + eventos de reversión/ajuste. Log inmutable en `audit.log_entries`. |
| **Eliminación** | **Nunca** `DELETE` en `ledger_entries`/`ledger_transactions`. `closed_at` en `ledger_accounts` para cuentas inactivas. Purga solo `idempotency_keys`/`outbox_events` por TTL. |

---

## 10. Decisiones Pendientes (Marcadas)

| Tema | Estado | Detalle |
|---|---|---|
| Hash chain tamper-evidence (`entry_hash`) | `DECIDIR` | Evaluar overhead vs. valor regulatorio |
| `balance_after` materializado en cada entry | `DECIDIR` | Trade-off storage vs. velocidad extractos |
| Particionado temporal `ledger_entries` (pg_partman) | `PENDIENTE` | Fase 3+ por volumen |
| Multi-moneda en una transacción (conversión implícita) | `NO DETERMINADO` | Requiere diseño FX engine |
| Cuentas "omnibus" vs. segregadas por cliente | `REQUIERE REGULACIÓN` | Jurisdicción-dependent |

---

*Fin del documento L-ledger-architecture.md*