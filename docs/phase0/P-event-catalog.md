# P — Catálogo de Eventos Inicial (Event Catalog)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)  
Proyecto: `MonedasAR` · Dominio: `[DOMAIN]` · Marca: `MonedasAR`

---

## 1. Envelope Canónico (Obligatorio en Todos los Eventos)

```json
{
  "event_id": "0192f7c0-7b3a-7f2a-8c4e-1a2b3c4d5e6f",        // UUIDv7, único global
  "event_type": "UserRegistered",                              // PascalCase, versión en schema_version
  "schema_version": 1,                                         // INT, obligatorio, incremental
  "aggregate_id": "0192f7c0-7b3a-7f2a-8c4e-1a2b3c4d5e6f",     // ID de la entidad raíz (user_id, account_id, etc.)
  "aggregate_type": "User",                                    // Nombre del agregado: User, Account, Order, Position, LedgerTransaction
  "timestamp": "2026-09-27T14:32:10.123456Z",                  // UTC, RFC3339 con micros
  "correlation_id": "0192f7c0-7b3a-7f2a-8c4e-1a2b3c4d5e6f",   // ID de request externo (trace end-to-end)
  "causation_id": "0192f7c0-7b3a-7f2a-8c4e-1a2b3c4d5e6f",     // ID del evento que causó este (chain)
  "producer": "identity",                                      // Servicio origen: identity, ledger, trading, risk, etc.
  "payload": {                                                 // Esquema versionado por event_type + schema_version
    "user_id": "0192f7c0-7b3a-7f2a-8c4e-1a2b3c4d5e6f",
    "email": "user@example.com",
    "mode": "DEMO"
  }
}
```

### 1.1 Reglas de Compatibilidad de Schema

| Regla | Descripción |
|---|---|
| **Additive only** | Nuevos campos `optional` + `default` en payload; nunca romper consumidores existentes |
| **`schema_version` obligatorio** | Todo evento lleva versión; consumidor debe manejar versiones que conoce y log/skip desconocidas |
| **No renombrar/borrar campos** | `DEPRECATED` en documentación; mantener en payload con valor `null` si ya no aplica |
| **Cambio breaking = nuevo `event_type`** | Ej: `OrderCreatedV2` (evitar; preferir additive) |
| **Registro central** | Catálogo en este documento + `audit.event_subscriptions` para discovery |

---

## 2. Catálogo Inicial (37 Eventos)

> **Clasificación de datos**: `PUBLIC` (sin datos sensibles), `INTERNAL` (operacional), `CONFIDENTIAL` (financiero/PII/regulatorio).  
> **Criticidad**: `CRITICAL` (dinero/riesgo/regulatorio), `HIGH` (core trading), `MEDIUM` (operacional), `LOW` (auditoría/analytics).

| # | Event Type | v | Producer | Consumers | Aggregate | Payload Mínimo (Campos Clave) | Clasificación | Criticidad |
|---|---|---|---|---|---|---|---|---|
| 1 | **UserRegistered** | 1 | identity | audit, notification, kyс | User | `user_id`, `email`, `mode`, `jurisdiction` | CONFIDENTIAL | HIGH |
| 2 | **UserEmailVerified** | 1 | identity | audit, notification | User | `user_id`, `email`, `verified_at` | INTERNAL | MEDIUM |
| 3 | **UserLoggedIn** | 1 | identity | audit, risk, notification | User | `user_id`, `session_id`, `ip`, `device_fingerprint`, `mfa_used` | CONFIDENTIAL | HIGH |
| 4 | **LoginFailed** | 1 | identity | audit, risk, notification | User | `user_id`, `email`, `ip`, `reason`, `attempt_count` | CONFIDENTIAL | HIGH |
| 5 | **MfaEnabled** | 1 | identity | audit, notification | User | `user_id`, `mfa_type` (totp/webauthn), `enabled_at` | CONFIDENTIAL | HIGH |
| 6 | **MfaDisabled** | 1 | identity | audit, notification | User | `user_id`, `mfa_type`, `disabled_at` | CONFIDENTIAL | HIGH |
| 7 | **SessionRevoked** | 1 | identity | audit, gateway | Session | `session_id`, `user_id`, `reason`, `revoked_by` (user/admin) | INTERNAL | MEDIUM |
| 8 | **PasswordResetRequested** | 1 | identity | audit, notification | User | `user_id`, `email`, `token_hash`, `expires_at` | CONFIDENTIAL | MEDIUM |
| 9 | **PasswordResetCompleted** | 1 | identity | audit, notification | User | `user_id`, `reset_at` | CONFIDENTIAL | HIGH |
| 10 | **ApiKeyCreated** | 1 | identity | audit, gateway | ApiKey | `api_key_id`, `user_id`, `name`, `scopes`, `expires_at`, `ip_whitelist` | CONFIDENTIAL | HIGH |
| 11 | **ApiKeyRevoked** | 1 | identity | audit, gateway | ApiKey | `api_key_id`, `user_id`, `revoked_at`, `reason` | CONFIDENTIAL | HIGH |
| 12 | **AccountCreated** | 1 | accounts | audit, wallet, ledger, risk, notification | TradingAccount | `account_id`, `user_id`, `type` (live/demo), `currency`, `jurisdiction`, `leverage` | CONFIDENTIAL | CRITICAL |
| 13 | **KycSubmitted** | 1 | kyc | audit, accounts, risk, notification | KycCase | `kyc_case_id`, `user_id`, `account_id`, `provider`, `document_types[]` | CONFIDENTIAL | CRITICAL |
| 14 | **KycApproved** | 1 | kyc | audit, accounts, wallet, trading, risk, notification | KycCase | `kyc_case_id`, `user_id`, `account_id`, `tier`, `approved_at`, `expires_at` | CONFIDENTIAL | CRITICAL |
| 15 | **KycRejected** | 1 | kyc | audit, accounts, notification | KycCase | `kyc_case_id`, `user_id`, `account_id`, `reason`, `retry_allowed` | CONFIDENTIAL | CRITICAL |
| 16 | **DemoAccountCreated** | 1 | accounts | audit, wallet, trading | TradingAccount | `account_id`, `user_id`, `initial_balance`, `currency`, `expires_at` | INTERNAL | MEDIUM |
| 17 | **DemoBalanceReset** | 1 | accounts | audit, wallet, trading, ledger | TradingAccount | `account_id`, `user_id`, `old_balance`, `new_balance`, `reset_at` | CONFIDENTIAL | MEDIUM |
| 18 | **DepositRequested** | 1 | payments | audit, wallet, ledger, risk, notification | Deposit | `deposit_id`, `user_id`, `account_id`, `amount`, `currency`, `psp`, `method`, `callback_url` | CONFIDENTIAL | CRITICAL |
| 19 | **DepositCompleted** | 1 | payments | audit, wallet, ledger, trading, risk, notification | Deposit | `deposit_id`, `user_id`, `account_id`, `amount`, `currency`, `psp_ref`, `ledger_tx_id`, `completed_at` | CONFIDENTIAL | CRITICAL |
| 20 | **DepositFailed** | 1 | payments | audit, wallet, risk, notification | Deposit | `deposit_id`, `user_id`, `account_id`, `amount`, `currency`, `error_code`, `error_msg`, `retryable` | CONFIDENTIAL | HIGH |
| 21 | **WithdrawalRequested** | 1 | payments | audit, wallet, ledger, risk, notification | Withdrawal | `withdrawal_id`, `user_id`, `account_id`, `amount`, `currency`, `psp`, `method`, `destination` | CONFIDENTIAL | CRITICAL |
| 22 | **WithdrawalApproved** | 1 | payments | audit, wallet, ledger, risk, notification | Withdrawal | `withdrawal_id`, `user_id`, `account_id`, `approved_at`, `approved_by` | CONFIDENTIAL | CRITICAL |
| 23 | **WithdrawalCompleted** | 1 | payments | audit, wallet, ledger, trading, risk, notification | Withdrawal | `withdrawal_id`, `user_id`, `account_id`, `amount`, `currency`, `psp_ref`, `ledger_tx_id`, `completed_at` | CONFIDENTIAL | CRITICAL |
| 24 | **WithdrawalRejected** | 1 | payments | audit, wallet, risk, notification | Withdrawal | `withdrawal_id`, `user_id`, `account_id`, `reason`, `retryable` | CONFIDENTIAL | HIGH |
| 25 | **OrderCreated** | 1 | trading | audit, risk, market-data, notification | Order | `order_id`, `account_id`, `symbol`, `side`, `type`, `quantity`, `price`, `stop_price`, `time_in_force`, `client_order_id` | CONFIDENTIAL | CRITICAL |
| 26 | **OrderAccepted** | 1 | trading | audit, risk, market-data, notification | Order | `order_id`, `account_id`, `accepted_at`, `exchange_order_id` | CONFIDENTIAL | CRITICAL |
| 27 | **OrderRejected** | 1 | trading | audit, risk, notification | Order | `order_id`, `account_id`, `reason`, `reject_code` | CONFIDENTIAL | HIGH |
| 28 | **OrderFilled** | 1 | trading | audit, wallet, ledger, risk, positions, notification | Order | `order_id`, `account_id`, `fill_id`, `filled_qty`, `avg_price`, `fee`, `fee_currency`, `ledger_tx_id`, `filled_at` | CONFIDENTIAL | CRITICAL |
| 29 | **OrderCancelled** | 1 | trading | audit, risk, notification | Order | `order_id`, `account_id`, `cancelled_qty`, `reason`, `cancelled_at` | CONFIDENTIAL | HIGH |
| 30 | **PositionOpened** | 1 | trading | audit, wallet, ledger, risk, notification | Position | `position_id`, `account_id`, `symbol`, `side`, `size`, `entry_price`, `margin_used`, `leverage`, `opened_at` | CONFIDENTIAL | CRITICAL |
| 31 | **PositionClosed** | 1 | trading | audit, wallet, ledger, risk, notification | Position | `position_id`, `account_id`, `symbol`, `close_price`, `realized_pnl`, `fee`, `ledger_tx_id`, `closed_at` | CONFIDENTIAL | CRITICAL |
| 32 | **MarginCallTriggered** | 1 | risk | audit, trading, wallet, notification | MarginAccount | `account_id`, `margin_level`, `threshold`, `required_margin`, `triggered_at` | CONFIDENTIAL | CRITICAL |
| 33 | **StopOutTriggered** | 1 | risk | audit, trading, wallet, ledger, notification | MarginAccount | `account_id`, `margin_level`, `positions_closed[]`, `total_pnl`, `triggered_at` | CONFIDENTIAL | CRITICAL |
| 34 | **RiskLimitExceeded** | 1 | risk | audit, trading, admin, notification | RiskLimit | `limit_id`, `account_id`, `limit_type`, `current_value`, `threshold`, `action_taken`, `timestamp` | CONFIDENTIAL | CRITICAL |
| 35 | **PnlRealized** | 1 | trading | audit, wallet, ledger, risk, notification | Position | `position_id`, `account_id`, `symbol`, `realized_pnl`, `currency`, `ledger_tx_id`, `realized_at` | CONFIDENTIAL | CRITICAL |
| 36 | **FeeCharged** | 1 | trading | audit, wallet, ledger, risk, notification | Order/Position | `charge_id`, `account_id`, `type` (commission/spread/financing), `amount`, `currency`, `ledger_tx_id`, `charged_at` | CONFIDENTIAL | CRITICAL |
| 37 | **SwapApplied** | 1 | trading | audit, wallet, ledger, risk, notification | Position | `swap_id`, `account_id`, `symbol`, `side`, `swap_points`, `amount`, `currency`, `ledger_tx_id`, `applied_at` | CONFIDENTIAL | CRITICAL |
| 38 | **LedgerPosted** | 1 | ledger | audit, wallet, risk, reporting, admin | LedgerTransaction | `transaction_id`, `type`, `correlation_id`, `occurred_at`, `entries[]` (account_id, direction, amount, currency) | CONFIDENTIAL | CRITICAL |

> **Total: 38 eventos** (supera mínimo 30). Eventos 1-11 = Fase 1 (identity). 12-17 = Fase 2 (accounts). 18-24 = Fase 2/6 (payments→wallet/ledger). 25-38 = Fase 4 (trading/risk/ledger).

---

## 3. Patrones de Publicación y Consumo

### 3.1 Transactional Outbox (Obligatorio)

```text
[Servicio] --(misma tx ACID)--> [Tabla outbox_events] --(poller/relay)--> [Redpanda/Kafka] --(consumers)--> [Servicios downstream]
```

- **Tabla outbox por servicio** (ej. `identity.outbox_events`, `ledger.outbox_events`)
- **Poller**: Lee `WHERE NOT published ORDER BY created_at LIMIT 100`, publica batch, marca `published=true` en misma tx
- **Garantía**: At-least-once delivery → **consumidor debe ser idempotente**

### 3.2 Particionado y Ordenamiento

| Tema | Partition Key | Justificación |
|---|---|---|
| `identity.events` | `aggregate_id` (user_id) | Orden por usuario: login → mfa → session |
| `ledger.events` | `aggregate_id` (transaction_id) | Unicidad por transacción |
| `trading.events` | `aggregate_id` (account_id) | Orden de órdenes/posiciones por cuenta |
| `risk.events` | `aggregate_id` (account_id) | Límites y margin calls por cuenta |
| `payments.events` | `aggregate_id` (deposit_id/withdrawal_id) | Flujo de vida del pago |

> **Regla**: Eventos del mismo agregado **siempre** en misma partición → orden garantizado.

### 3.3 Idempotencia de Consumidor (Deduplicación)

```python
# Patrón estándar en cada consumidor
async def handle_event(event: EventEnvelope, session: AsyncSession):
    # 1. Verificar si ya procesado (tabla de control por consumidor)
    processed = await session.execute(
        "SELECT 1 FROM consumer_processed_events WHERE consumer = $1 AND event_id = $2",
        "wallet_service",
        event.event_id,
    )
    if processed.scalar():
        return  # Duplicate, acknowledge

    # 2. Procesar lógica de negocio
    await process_business_logic(event)

    # 3. Registrar procesamiento (misma tx que lógica)
    await session.execute(
        "INSERT INTO consumer_processed_events (consumer, event_id, processed_at) VALUES ($1, $2, $3)",
        "wallet_service",
        event.event_id,
        now(),
    )
```

- Tabla `consumer_processed_events` por servicio consumidor (o compartida con PK `(consumer, event_id)`)
- TTL opcional (ej. 30 días) si volumen alto; `event_id` UUIDv7 → monotonically increasing → range delete eficiente

### 3.4 Dead Letter Queue (DLQ)

| Condición | Acción |
|---|---|
| Deserialización falla (schema mismatch) | → DLQ topic `*.dlq` + alerta inmediata |
| Procesamiento falla tras 3 reintentos (backoff exponencial) | → DLQ + alerta |
| Evento `schema_version` no soportado | Log warning + skip (no DLQ) — consumidor actualiza versión |
| Evento `event_type` desconocido | Log info + skip (no DLQ) — nuevo evento añadido |

**DLQ Payload**: Envelope original + `error`, `retry_count`, `failed_at`, `consumer`.

### 3.5 Retención de Eventos en Redpanda

| Topic | Retención | Limpieza |
|---|---|---|
| `identity.events` | 90 días | `delete` |
| `ledger.events` | **7 años** (regulatorio) | `compact` + `delete` |
| `trading.events` | 2 años | `delete` |
| `risk.events` | 7 años | `compact` + `delete` |
| `payments.events` | 7 años | `compact` + `delete` |
| `kyc.events` | 7 años | `compact` + `delete` |
| `audit.events` | 7 años | `compact` (log inmutable) |
| `*.dlq` | 30 días | `delete` (tras investigación) |

> `compact` = log compaction por `event_id` (último valor por clave).

---

## 4. Eventos Sensibles — Clasificación de Datos (Resumen)

| Event Type | Clasificación | Campos Sensibles en Payload | Tratamiento Especial |
|---|---|---|---|
| UserRegistered | CONFIDENTIAL | `email`, `jurisdiction` | Cifrar en tránsito (TLS); no loggear payload completo en texto plano |
| UserLoggedIn | CONFIDENTIAL | `ip`, `device_fingerprint` | Hash IP en logs; `device_fingerprint` solo para risk |
| LoginFailed | CONFIDENTIAL | `email`, `ip` | No exponer `email` en métricas; alerta por IP |
| MfaEnabled/Disabled | CONFIDENTIAL | `mfa_type` | Auditar cambios de seguridad |
| ApiKeyCreated/Revoked | CONFIDENTIAL | `scopes`, `ip_whitelist` | `api_key` **nunca** en evento (solo `api_key_id`); secret solo en respuesta creación |
| AccountCreated | CONFIDENTIAL | `jurisdiction`, `leverage` | Datos regulatorios |
| KycSubmitted/Approved/Rejected | CONFIDENTIAL | `document_types`, `tier`, `provider` | PII máximo; acceso solo compliance/risk |
| Deposit/Withdrawal * | CONFIDENTIAL | `amount`, `currency`, `psp_ref`, `destination` | Dinero → máximo nivel |
| Order/Position * | CONFIDENTIAL | `quantity`, `price`, `pnl`, `margin` | Posiciones y riesgo |
| MarginCall/StopOut | CONFIDENTIAL | `margin_level`, `positions_closed` | Crítico riesgo |
| RiskLimitExceeded | CONFIDENTIAL | `current_value`, `threshold`, `action_taken` | Auditoría regulatoria |
| FeeCharged/SwapApplied | CONFIDENTIAL | `amount`, `currency` | Ingresos/gastos |
| LedgerPosted | CONFIDENTIAL | `entries[]` (cuentas, importes) | **Fuente de verdad financiera** — máximo control |

> **Regla**: Eventos `CONFIDENTIAL` → **nunca** en logs de aplicación en texto plano. Usar structured logging con `event_type` + `event_id` + `aggregate_id` solamente. Payload completo solo en `audit.log_entries` (cifrado en reposo).

---

## 5. Convenciones de Naming y Versionado

| Convención | Ejemplo |
|---|---|
| `event_type`: `PascalCase`, sustantivo + verbo pasado | `OrderFilled`, `DepositCompleted` |
| `aggregate_type`: Singular, PascalCase | `User`, `Order`, `Position`, `LedgerTransaction` |
| `producer`: lowercase, nombre del servicio | `identity`, `trading`, `ledger` |
| `schema_version`: Entero incremental desde 1 | `1`, `2`, `3` |
| Nuevo campo en payload: `optional`, `snake_case`, documentado | `new_optional_field?: string` |
| Deprecación: marcar en catálogo, mantener 2 versiones mínimas | `DEPRECATED since v2` en docs |

---

## 6. Decisiones Pendientes (Marcadas)

| Tema | Estado | Detalle |
|---|---|---|
| Schema registry formal (Confluent/Avro/Protobuf) | `DECIDIR` Fase 3 | JSON Schema en `audit.event_subscriptions` por ahora |
| Event sourcing completo para agregados (Order, Position) | `NO DETERMINADO` | Evaluar complejidad vs. CQRS actual |
| Exactly-once semantics (transactions outbox + consumer) | `DECIDIR` | Requiere idempotency keys en consumidores + deduplicación |
| Event replay tooling (CLI/UI) | `PENDIENTE` | Para debugging, reconciliación, migraciones |
| Encriptación payload CONFIDENTIAL en Redpanda | `DECIDIR` | TLS en tránsito sí; en reposo: Redpanda encryption o application-level |

---

## 7. Referencia Rápida: Eventos por Servicio Productor

| Servicio | Eventos (cuenta) |
|---|---|
| `identity` | 11 (1–11) |
| `accounts` | 4 (12, 16–17) |
| `kyc` | 3 (13–15) |
| `payments` | 7 (18–24) |
| `trading` | 10 (25–31, 35–37) |
| `risk` | 3 (32–34) |
| `ledger` | 1 (38) |

---

*Fin del documento P-event-catalog.md*