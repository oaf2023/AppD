# I — Arquitectura de Pagos (Depósitos y Retiros)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `MonedasAR` · Dominio: `[DOMAIN]` · Marca: `MonedasAR`

> **Regla de lectura**: diseño objetivo, no afirmación de implementación. Servicio `payments` asignado a **Fase 6** (`00-decisions.md` §3), schema PostgreSQL propio `payments` (ADR-0005, `O-database-strategy.md`). Estados reales por componente (`IMPLEMENTADO`/`PARCIAL`/`MOCK`/`PENDIENTE`/`REQUIERE PROVEEDOR`/`REQUIERE LICENCIA`): `W-build-now.md` y `X-blocked-to-live.md`. Eventos: catálogo `P-event-catalog.md` (#18–#24, #38). Asientos: `L-ledger-architecture.md` §7.2/§7.3. Rutas: `Q-api-map.md` §2.13. **No se nombran proveedores concretos**: solo categorías de proveedor.

---

## 1. Principios inmutables

| # | Principio | Implementación |
|---|---|---|
| 1 | **Ningún proveedor se acopla al núcleo** | Core solo con interfaces (`PaymentProviderAdapter`, `PaymentMethodRegistry`, `ProviderWebhookReceiver`); proveedores viven en `adapters/` tras la interface. Prohibido importar SDKs de PSP fuera del paquete adapter |
| 2 | **Dinero: solo `Decimal`/`NUMERIC(38,18)`** | Nunca `float`; `amount_minor BIGINT` opcional para monedas con unidad mínima (`00-decisions.md` §5) |
| 3 | **Ledger = fuente de verdad** | Acreditación solo tras asiento double-entry idempotente (`ledger`); `wallet` es proyección (`L`) |
| 4 | **Idempotencia obligatoria** | `Idempotency-Key` + SHA-256 de payload + respuesta almacenada en depósitos, retiros, webhooks y postings (ADR-0010) |
| 5 | **Toda comprobación es server-side** | Ningún estado, MFA, saldo, límite o aprobación se acepta del cliente; el frontend solo solicita |
| 6 | **Auditabilidad extremo a extremo** | `correlation_id` + `causation_id` en cada fila y evento; payload crudo del webhook conservado |
| 7 | **Sin ficción** | Sin PSP, licencia o rail real → adapter `MOCK` + placeholder de config; ver `X-blocked-to-live.md` |
| 8 | **Modo explícito** | `DEMO` vs `LIVE` (`feature_flag live_trading=false`); en Fase 1–5 todo flujo corre en simulación etiquetada |

---

## 2. Capa de abstracción

### 2.1 `PaymentProviderAdapter` (interface única de salida a un proveedor)

```python
# services/payments/app/providers/base.py  (Python 3.13, Pydantic v2)
class PaymentProviderAdapter(Protocol):
    provider_code: str  # identificador opaco de config, p.ej. 'prov_a' — no expone marca al core
    provider_category: ProviderCategory  # card_acquirer | bank_rail | crypto_rail | local_wallet | e_money_issuer
    capabilities: frozenset[Capability]  # DEPOSIT_INTENT | WITHDRAWAL | WEBHOOK_HMAC | FEE_QUOTE | CANCEL | POLL_STATUS

    async def create_deposit_intent(self, req: DepositIntentRequest) -> DepositIntentResult: ...
    async def get_status(self, ref: ProviderRef) -> ProviderStatusResult: ...  # polling / fuente de verdad server-side
    def verify_webhook_signature(
        self, raw_body: bytes, headers: Mapping[str, str], secret: SecretStr
    ) -> None: ...  # lanza SignatureError si falla
    async def request_withdrawal(self, req: ProviderWithdrawalRequest) -> ProviderWithdrawalResult: ...
    async def cancel(self, ref: ProviderRef, reason: str) -> CancelResult: ...
    async def quote_fee(self, req: FeeQuoteRequest) -> FeeQuote: ...  # fee + currency + desglose + expires_at
```

| Elemento | Contrato |
|---|---|
| `DepositIntentRequest` | `deposit_id` (UUIDv7), `amount`, `currency`, `method_code`, `return_url`, `idempotency_key`, `metadata` (sin PII innecesaria) |
| `DepositIntentResult` | `provider_ref`, `redirect_action \| qr_action \| reference_action`, `expires_at`, `fee_quote`, `raw_payload_ref` |
| `ProviderStatusResult` | `provider_state` normalizado (`requires_action`, `pending`, `succeeded`, `failed`, `cancelled`, `expired`), `amount`, `currency`, `provider_ref`, `settled_at`, `failure_code` |
| `ProviderWithdrawalRequest` | `withdrawal_id`, `amount`, `currency`, `destination_token` (tokenizado; **nunca** PAN/CVV), `beneficiary_ref`, `idempotency_key` |
| `FeeQuote` | `total`, `fee`, `currency`, `rate_source` (`DETERMINISTIC \| PROVIDER \| FX_SERVICE`), `breakdown[]`, `quoted_at`, `expires_at` |
| `ProviderRef` | envoltorio opaco `{provider_code, provider_ref, external_ref}` — el core no interpreta su formato |

**Taxonomía de errores normalizada** (todo adapter debe mapear a ella): `AUTH_FAILED | RATE_LIMITED | NETWORK_TIMEOUT | VALIDATION_REJECTED | PROVIDER_DECLINED | PROVIDER_UNAVAILABLE | WEBHOOK_SIGNATURE_INVALID`, con atributo `retryable: bool`. El core jamás ramifica sobre tipos del proveedor, solo sobre esta taxonomía.

**Garantías del adaptador**: timeout por operación (`timeout_ms` de config), retries solo en `retryable` con backoff exponencial + jitter, circuit breaker por `provider_code`, sin estado entre llamadas (stateless), todo I/O trazado con `correlation_id`.

### 2.2 `PaymentMethodRegistry` (métodos por moneda/jurisdicción)

```python
class PaymentMethodRegistry(Protocol):
    async def resolve(
        self, *, currency: str, jurisdiction: str, amount: Decimal, kyc_tier: str, mode: Literal["DEMO", "LIVE"]
    ) -> list[PaymentMethodOffer]: ...
    async def get_fee_quote(self, method_code: str, amount: Decimal, currency: str) -> FeeQuote: ...
    def register(self, method: PaymentMethodConfig) -> None: ...  # carga desde tabla payment_method (no en código)
```

| Regla | Detalle |
|---|---|
| Fuente de verdad | Tabla `payment_method` + `payment_provider_config` (config, no código); alta/baja por backoffice, auditado |
| Claves de resolución | `currency` × `jurisdiction` × `method_type` × `kyc_tier` × `mode` × vigencia temporal |
| Orden | `priority` desc, luego fee total asc; inactivos o fuera de vigencia excluidos |
| Jurisdicción | La lista de métodos permitidos la determina el **Jurisdiction Rules Engine** (`J-kyc-aml-architecture.md` §5); el registry solo filtra lo que el motor autoriza |
| Campos derivados | Mínimo/máximo por transacción y por día, `settlement_expectation`, `requires_kyc_tier`, `cutoff` |
| Respuesta a cliente | `GET /api/v1/payment-methods` devuelve solo ofertas resueltas; **jamás** config interna ni secretos |

### 2.3 `ProviderWebhookReceiver` (recepción de callbacks del proveedor)

Ruta: `POST /api/v1/payments/webhooks/{provider}` (`Q-api-map.md`) — **sin JWT**: autenticación = firma del proveedor.

```python
class ProviderWebhookReceiver(Protocol):
    async def receive(
        self, provider_code: str, raw_body: bytes, headers: Mapping[str, str], request_id: str
    ) -> WebhookAck: ...
```

Pipeline obligatorio, en este orden:

```text
1. leer RAW BODY (bytes, sin re-serializar)     → 2. firma HMAC/verificación (adapter)      → 3. ventana de timestamp anti-replay
4. deduplicación por (provider_config_id, provider_event_id) UNIQUE   → 5. persistir payload crudo + headers + hash (webhook_event)
6. encolar procesamiento asíncrono (respuesta 2xx inmediata al proveedor)  → 7. aplicar máquina de estados del depósito/retiro
8. si falla 3 veces → DLQ `payments.dlq` + alerta                          → 9. reconciliación posterior (reconciliation_run)
```

| Propiedad | Regla |
|---|---|
| Firma | Obligatoria; comparación en tiempo constante; secreto por `provider_config_id`, rotación con ventana de doble secreto |
| Idempotencia | Duplicado → `200 OK` sin reprocesar (fila `webhook_event` marcada `duplicate`) |
| Orden | Se aplica **guarda de máquina de estados**: transición inválida/out-of-order se persiste con `out_of_order=true`, no muta el agregado, y se resuelve vía `get_status` + reconciliación |
| Ack rápido | El proveedor recibe 2xx en <1 s; el procesamiento real es asíncrono (colas) |
| Fallo | 3 intentos con backoff → DLQ + alerta; replay manual tool (`PENDIENTE`) |
| Seguridad | Rate limit por IP y por `provider_config_id`; payload crudo **nunca** en logs de aplicación en texto plano (evento `CONFIDENTIAL`/`RESTRICTED`) |

---

## 3. Workflow de depósito

Ruta: `POST /api/v1/deposits` (sesión + `Idempotency-Key` + KYC vigente). Estado interno: `deposit.state`.

```text
REQUEST → PROVIDER → PENDING → CALLBACK/WEBHOOK → VALIDATION → AML/RISK → LEDGER → CREDITED
                                                                        └→ (hold manual / FAILED)
```

| # | Estado | Descripción | Quién emite/ejecuta | Evento catálogo P |
|---|---|---|---|---|
| 1 | `REQUEST` | Solicitud recibida; se inserta `deposit` + idempotencia en misma tx | `payments` (API handler, vía `gateway`) | **#18 `DepositRequested`** (outbox en mismo commit) |
| 2 | `PROVIDER` | `create_deposit_intent()` al adapter; se guarda `provider_ref` | `payments` (adapter) | — (transición interna) |
| 3 | `PENDING` | Intent creado; esperando pago del usuario (redirect/QR/referencia) | `payments` | — |
| 4 | `CALLBACK` | Webhook recibido: firma → timestamp → dedup → payload crudo | `proveedor` (externo) → `ProviderWebhookReceiver` | — (registra `webhook_event`) |
| 5 | `VALIDATION` | Confirmación **server-side** con `get_status()`: monto, moneda, `provider_ref`, estado coincidente | `payments` (poller) | — |
| 6 | `AML/RISK` | Motor de reglas: velocidad, umbral, jurisdicción, dispositivo; puede poner `hold` | `payments` + `risk` (eventos) | — |
| 7 | `LEDGER` | Posting double-entry (L §7.2) idempotente: `RECEIVABLE.PSP` / `PAYABLE.CLIENT` | `ledger` (API interna) | **#38 `LedgerPosted`** (producer: `ledger`) |
| 8 | `CREDITED` | Consumidor de `LedgerPosted` confirma; proyección `wallet` actualizada; notificación | `payments` (consumer) | **#19 `DepositCompleted`** |
| — | `FAILED` | Error terminal (adapter, validación, AML, expiración) | `payments` | **#20 `DepositFailed`** (`retryable` según causa) |

### 3.1 Transiciones válidas

| De → A | Condición | Evento emitido | Emisor |
|---|---|---|---|
| `REQUEST → PROVIDER` | Validación de entrada OK (monto, método, KYC, jurisdicción) | #18 | `payments` |
| `REQUEST → FAILED` | Método no permitido / KYC no vigente / límite excedido | #20 | `payments` |
| `PROVIDER → PENDING` | `create_deposit_intent` exitoso | — | `payments` |
| `PROVIDER → FAILED` | Adapter devuelve error no recuperable o timeout tras retries | #20 | `payments` |
| `PENDING → CALLBACK` | Webhook con firma válida y no duplicado | — | receptor (origen: proveedor) |
| `PENDING → FAILED` | `expires_at` superado sin pago | #20 (`retryable=true`) | `payments` (job) |
| `CALLBACK → VALIDATION` | Encolado tras persistir payload | — | `payments` |
| `VALIDATION → AML/RISK` | `get_status = succeeded` y montos coinciden | — | `payments` |
| `VALIDATION → FAILED` | Monto/moneda/ref discordantes o `failed`/`cancelled` | #20 | `payments` |
| `AML/RISK → LEDGER` | Reglas en `LOW/MEDIUM` sin hit → llamada a `ledger` | — | `payments` |
| `AML/RISK → hold` (`under_review`) | `HIGH/CRITICAL` o umbral → caso manual; no se acredita | — (sin evento en P) | `payments` → backoffice |
| `LEDGER → CREDITED` | `LedgerPosted` confirmado y balance consistente | #19 | `payments` |
| `FAILED → REQUEST` | Reintento del usuario = **nuevo** `deposit_id` (nueva clave de idempotencia) | #18 | `payments` |

**Reglas de orden**: partición Redpanda `payments.events` por `aggregate_id = deposit_id` → orden por depósito garantizado; consumidores idempotentes con `consumer_processed_events`; `at-least-once`.

**Transiciones prohibidas**: `CREDITED → cualquier`, `LEDGER → FAILED` (un asiento confirmado se corrige solo con transacción `reversal` en ledger, L §3), saltos `PENDING → LEDGER` (sin validación server-side), reacreditación (dedup + idempotencia).

**Sin evento propio en P**: las transiciones intermedias (2–7) no tienen `event_type` en el catálogo; se registran en `deposit.state` + `audit.log_entries`. Si se desea publicarlas, requiere **enmienda additiva** de `P-event-catalog.md` → `DECIDIR`.

**Reversión/chargeback**: fuera del flujo normal; asiento `reversal` (L §3) + estado `REVERSED` → `DECIDIR` (enmienda de catálogo + política de disputas) y bloqueo documentado en `X-blocked-to-live.md`.

---

## 4. Workflow de retiro

Ruta: `POST /api/v1/withdrawals` (sesión + **step-up MFA** + `Idempotency-Key`).

```text
REQUEST → MFA → VALIDATE BALANCE → RESERVE FUNDS → AML → FRAUD CHECK
        → APPROVAL RULES (maker-checker por importe/riesgo) → PROVIDER → SETTLEMENT → LEDGER → COMPLETE
```

Estados canónicos: `pending | under_review | approved | processing | completed | failed | rejected | cancelled`.

| Etapa | Qué ocurre server-side | Estado resultante | Evento P | Fallo → |
|---|---|---|---|---|
| 1. `REQUEST` | Valida pertenencia de cuenta, `Idempotency-Key`, método/jurisdicción vía registry + motor de reglas; inserta `withdrawal` | `pending` | **#21 `WithdrawalRequested`** (`payments`, outbox) | `rejected` + **#24** (`reason`, `retryable`) |
| 2. `MFA` | Verificación TOTP **en `identity`**; el servidor exige step-up, nunca confía en flag cliente | `pending` | — | `rejected` + #24 (`mfa_failed`) |
| 3. `VALIDATE BALANCE` | Saldo disponible calculado del **ledger** (no solo de la proyección `wallet`); cobertura de fee | `pending` | — | `rejected` + #24 (`insufficient_funds`) |
| 4. `RESERVE FUNDS` | Reserva/hold del importe: `FOR UPDATE` en `wallet.balances` + `advisory_lock(account_id)` (`O-database-strategy`); doble gasto imposible | `pending` (reservado) | — | `rejected` + #24 (libera nada, no había reserva) |
| 5. `AML` | Screening del beneficiario + monitorización transaccional; hold si hit o umbral | `under_review` | — | `rejected` + #24 (`aml_block`) |
| 6. `FRAUD CHECK` | Velocity, dispositivo, beneficiario nuevo, geolocalización declarada vs IP (señal, nunca determinante) | `under_review` | — | `rejected` + #24 (`fraud_rule`) |
| 7. `APPROVAL RULES` | Maker-checker por importe/riesgo/jurisdicción → tabla `withdrawal_approval`; auto-aprueba solo si LOW + bajo umbral + destino allowlist | `approved` | **#22 `WithdrawalApproved`** (`approved_at`, `approved_by`) | `under_review` (SLA) o `rejected` + #24 |
| 8. `PROVIDER` | `request_withdrawal()` con idempotencia **hacia el proveedor** (token anti-doble-pago) | `processing` | — | `failed` + #24 (libera reserva) |
| 9. `SETTLEMENT` | Webhook/`get_status` confirma liquidación; se compara monto/moneda/`provider_ref` | `processing` | — | `failed` + #24 |
| 10. `LEDGER` | Posting L §7.3: `PAYABLE.CLIENT` → `PAYABLE.PSP`; al asentarse, `PAYABLE.PSP` → `CASH` | `completed` | **#38 `LedgerPosted`** (`ledger`) | — |
| 11. `COMPLETE` | Notificación + cierre; se libera cualquier resto de reserva | `completed` | **#23 `WithdrawalCompleted`** (`payments`) | — |

| Transiciones válidas | |
|---|---|
| `pending → under_review \| approved \| rejected \| cancelled` | etapas 2–7 |
| `under_review → approved \| rejected \| cancelled` | decisión humana/reglas |
| `approved → processing \| failed \| cancelled` | llamada al proveedor |
| `processing → completed \| failed` | settlement |
| `completed`, `rejected`, `failed`, `cancelled` | **terminales** (cancelación solo antes de `processing`) |

### 4.1 Idempotencia y anti-doble-pago (obligatorio)

| Capa | Mecanismo |
|---|---|
| API | `Idempotency-Key` + `request_hash` (SHA-256) + respuesta persistida; misma clave + distinto hash → `409 IDEMPOTENCY_CONFLICT`; `UNIQUE (user_id, idempotency_key)` |
| Dominio | `UNIQUE` parcial: un solo retiro activo por (`account_id`, clave); doble POST concurrente → segunda respuesta idéntica sin efecto lateral (REQ-020) |
| Ledger | `ledger_idempotency_keys` (L §6): misma clave → misma `transaction_id` |
| Proveedor | `withdrawal_id` enviado como token de idempotencia al adapter; reintento = mismo token, nunca payout nuevo |
| Webhook | Dedup por `provider_event_id` (§5) |

**Invariante**: ninguna retirada alcanza `processing` sin: MFA verificado + saldo validado en ledger + reserva activa + AML/fraud resueltos + aprobación registrada (si la regla lo exige). Test obligatorio de reintento concurrente → **un solo payout**.

---

## 5. Seguridad de webhooks

| Control | Especificación |
|---|---|
| **Firma obligatoria** | HMAC (SHA-256 u otro, según `hmac_algo` de config) sobre `timestamp + "." + raw_body`; comparación en tiempo constante; sin secreto válido → `401`, sin procesar. Secreto solo en env/secret manager (`REQUIERE PROVEEDOR` KMS/Vault en producción), **nunca** en repo/logs/frontend |
| **Ventana anti-replay** | Header de timestamp obligatorio; fuera de ±`WINDOW_SEC` (`DECIDIR`, inicio: 300 s) → rechazo + contador de alerta; `nonce`/`event_id` impide repetición dentro de la ventana |
| **Deduplicación** | `UNIQUE (provider_config_id, provider_event_id)`; duplicado → ack `200` sin reprocesar, fila en estado `duplicate` |
| **Payload crudo** | `webhook_event.payload_raw` (bytes) + `payload_hash` SHA-256 + headers relevantes + `source_ip`, conservados para auditoría; cifrado en reposo; nunca en logs en claro |
| **Orden** | Guarda de máquina de estados (§2.3); out-of-order se persiste pero no aplica; se resuelve con `get_status` + reconciliación |
| **Reintentos (entrante)** | El proveedor reintenta; nosotros ack rápido y procesamos async; fallo de procesamiento → 3 intentos con backoff → `payments.dlq` + alerta (`P-event-catalog` §3.4) |
| **Reintentos (saliente)** | `get_status`/`request_withdrawal`: backoff exponencial + jitter, tope de intentos, circuit breaker por `provider_code` |
| **Reconciliación** | Job `reconciliation_run` periódico (diario + on-demand): descarga registros del proveedor, match por `provider_ref`/monto/moneda/fecha, produce `matched/mismatched`; discrepancias → alerta + caso manual; **nunca** auto-acredita sin regla explícita y trazabilidad |
| **Seguridad perimetral** | Rate limit por IP y por proveedor (`gateway`), allowlist de origen cuando el proveedor lo soporta (`DECIDIR`), `request_id` en toda respuesta |

---

## 6. Modelo de datos previsto (schema `payments`)

> Montos: `NUMERIC(38,18)`; IDs: UUIDv7; toda fila lleva `correlation_id` y `created_at` UTC. Clasificación: `CONFIDENTIAL` = financiero/PII operativo; `RESTRICTED` = dinero + PII sensible o secretos.

| Tabla | Columnas clave | Clasificación |
|---|---|---|
| `payment_provider_config` | `id`, `provider_code` (opaco, único), `provider_category` (categoría, no marca), `environment` (sandbox/live), `base_url`, `auth_type`, `webhook_secret_ref` (referencia a secret manager, **nunca** valor en claro), `hmac_algo`, `timestamp_header_name`, `allowed_currencies[]`, `allowed_jurisdictions[]`, `timeout_ms`, `max_retries`, `cb_failure_threshold`, `cb_cooldown_seconds`, `is_active`, `config_version`, `created_by`, `updated_by`, `created_at`, `updated_at` | **RESTRICTED** (config con secretos/endpoint) |
| `payment_method` | `id`, `code`, `provider_config_id FK`, `method_type` (card/bank_transfer/crypto/local_wallet/e_money), `currency`, `jurisdiction`, `min_amount`, `max_amount`, `daily_max`, `fee_schedule_ref`, `settlement_expectation`, `requires_kyc_tier`, `priority`, `is_active`, `valid_from`, `valid_to` | **CONFIDENTIAL** (config financiera) |
| `deposit` | `id`, `user_id`, `account_id`, `amount`, `amount_minor`, `currency`, `method_id FK`, `provider_config_id FK`, `state`, `idempotency_key`, `request_hash`, `provider_ref`, `psp_ref`, `risk_score`, `risk_level`, `aml_status`, `hold_reason`, `ledger_tx_id`, `failure_code`, `failure_msg`, `retryable`, `correlation_id`, `causation_id`, `created_at`, `updated_at`, `completed_at` | **CONFIDENTIAL** (dinero) |
| `withdrawal` | `id`, `user_id`, `account_id`, `amount`, `currency`, `method_id FK`, `destination_token` (tokenizado), `destination_masked` (p.ej. `••••1234`), `beneficiary_ref`, `state`, `mfa_verified_at`, `balance_validated_at`, `reservation_id`, `aml_status`, `fraud_status`, `risk_level`, `approval_id FK`, `provider_config_id FK`, `provider_ref`, `idempotency_key`, `request_hash`, `ledger_tx_id`, `failure_code`, `retryable`, `correlation_id`, `causation_id`, `created_at`, `updated_at`, `completed_at` | **RESTRICTED** (dinero + beneficiario/destino = PII) |
| `provider_transaction` | `id`, `provider_config_id FK`, `direction` (deposit/withdrawal), `deposit_id FK NULL`, `withdrawal_id FK NULL`, `provider_ref`, `provider_state`, `amount`, `currency`, `request_payload_ref`, `response_payload_ref` (object storage `REQUIERE PROVEEDOR`), `attempt`, `latency_ms`, `error_code`, `retryable`, `last_polled_at`, `created_at`, `updated_at` | **CONFIDENTIAL** |
| `webhook_event` | `id`, `provider_config_id FK`, `provider_event_id`, `signature`, `signature_valid`, `timestamp_header`, `received_at`, `source_ip`, `headers` (recortados), `payload_raw`, `payload_hash`, `processing_status` (received/processed/duplicate/rejected/out_of_order/dlq), `retry_count`, `deposit_id FK NULL`, `withdrawal_id FK NULL`, `error`, `processed_at`, `UNIQUE (provider_config_id, provider_event_id)` | **RESTRICTED** (payload crudo del proveedor: puede contener datos de cuenta e IP) |
| `reconciliation_run` | `id`, `provider_config_id FK`, `scope` (deposits/withdrawals/balances), `period_from`, `period_to`, `started_at`, `finished_at`, `status` (running/completed/failed), `items_provider`, `items_internal`, `matched`, `mismatched`, `amount_provider_total`, `amount_internal_total`, `diff_amount`, `mismatch_details`, `report_ref`, `initiated_by` (system/user), `created_at` | **CONFIDENTIAL** (totales financieros) |
| `withdrawal_approval` | `id`, `withdrawal_id FK`, `rule_id`, `rule_version`, `threshold_amount`, `required_approvers`, `maker_id` (solicitante/creador), `checker_1_id`, `checker_1_decision`, `checker_1_at`, `checker_2_id` (NULL), `checker_2_decision`, `decision` (pending/approved/rejected), `reason`, `evidence_ref`, `sla_due_at`, `decided_at`, `correlation_id` | **RESTRICTED** (decisiones de cumplimiento + operadores) |

Índices críticos: `deposit (user_id, created_at DESC)`, `deposit (state, created_at) WHERE state NOT IN ('CREDITED','FAILED')` (poller), `withdrawal (state, created_at)`, `withdrawal (provider_ref)`, `webhook_event (received_at)`, `reconciliation_run (provider_config_id, period_from)`.

**Relación con `wallet`/`ledger`**: `deposit`/`withdrawal` solo referencian por ID; sin joins entre schemas (ADR-0005). La reserva del retiro se consulta vía API de `wallet`; el saldo vía API de `ledger`.

---

## 7. Fraude y AML en el flujo

| Control | Mecanismo | Dónde actúa |
|---|---|---|
| **Límites de velocidad** | Ventanas deslizantes en Redis: nº e importe de depósitos/retiros por `user_id`, `account_id`, IP y dispositivo; umbrales desde config + `jurisdiction_rule`; superación → `under_review` o bloqueo | etapa AML/RISK (depósito), etapas 1/6 (retiro) |
| **Beneficiario nuevo** | Primer retiro a un destino o cambio de destino → `beneficiary_first_use=true`: cooling-off (`DECIDIR`), límite reducido, verificación de titularidad (REQ-097), aprobación maker-checker obligatoria, allowlist | etapa 6–7 (retiro) |
| **Motor de reglas** | Entradas: importe, moneda, jurisdicción, tier KYC, antigüedad de la cuenta, patrón histórico, dispositivo, screening. Salida: `risk_level ∈ {LOW, MEDIUM, HIGH, CRITICAL}` + `action ∈ {allow, review, block, step_up}` + `rule_id` + `rule_version` + hash de entradas | depósito y retiro |
| **Revisión humana trazable** | `HIGH/CRITICAL` → caso con `sla_due_at`, aprobador distinto del creador (maker-checker), `reason` obligatorio, `evidence_ref`, actor + timestamp + antes/después en `audit.log_entries` (append-only) | etapa 7 (retiro), hold de depósito |
| **Hold de depósito** | Acreditación **suspendida** hasta resolución manual; no se postea al ledger | etapa `AML/RISK` |
| **Screening** | Sanciones/PEP de beneficiario en primer uso y en cambio: `REQUIERE PROVEEDOR`; ver `J-kyc-aml-architecture.md` §6 (adapter MOCK + flujo manual auditado) | etapa 5 (retiro) |
| **Reporting sospecha** | Alerta/escalado a Compliance; filing regulatorio (SAR/CTR) = `REQUIERE LICENCIA` + jurisdicción `DECIDIR` | post-flujo |

**Regla**: ningún `risk_level=HIGH|CRITICAL` se auto-aprueba; ningún cambio de regla es silencioso (versionado + autor + diff, como `jurisdiction_rule`).

---

## 8. PCI — datos de tarjeta

| Regla | Detalle |
|---|---|
| **Nunca almacenar PAN ni CVV** | Ni en BD, ni en logs, ni en eventos, ni en object storage, ni en `webhook_event.payload_raw` si puede evitarse (si el proveedor los envía: redacción/máscara al ingerir, política de minimización) |
| **Tokenización** | `REQUIERE PROVEEDOR`: el core solo maneja tokens/red de red del proveedor (`destination_token`, `provider_ref`) |
| **Captura** | Solo en campos alojados por el proveedor (hosted fields/redirect/QR); la plataforma no toca la tarjeta en Fase 1–6 |
| **Alcance PCI** | Determinado por el modo de integración → `DECIDIR` al elegir proveedor; documentar SAQ aplicable en `X-blocked-to-live.md`; ningún texto de este documento afirma certificación |
| **Verificación** | Test automatizado que falla si cualquier columna/log/evento contiene patrón PAN (Luhn) o `cvv` |

---

## 9. Gobernanza de datos (DAMA-DMBOK breve)

| Dimensión | Decisión |
|---|---|
| **Owner** | equipo `payments` (data owner: Head of Payments) |
| **Steward** | Head of Payments (operacional) + Compliance (retención/auditoría) |
| **Clasificación** | `CONFIDENTIAL` (depósitos, proveedores, conciliación) / `RESTRICTED` (retiros, destino, payload de webhook, config con secretos) |
| **Schema/contrato** | Este documento + migraciones versionadas en `services/payments/migrations`; cambios de columnas = migración + ADR si rompe contrato |
| **Calidad** | `amount>0`, moneda ISO 4217, `state` en enum, FK obligatorias, unicidad de idempotencia, checksum de payload |
| **Retención** | `deposit`/`withdrawal`/`provider_transaction`/`webhook_event`/`reconciliation_run`/**7 años** (coherente con retención de `payments.events` y del dominio, `D-domain-map` §retención); `idempotency` TTL 7 días; `outbox_events` TTL 30 días tras publicar; DLQ 30 días |
| **Permisos** | `payments` R/W sobre su schema; `wallet`/`ledger`/`risk` vía API; `admin` READ + acciones de aprobación con registro; ningún acceso cruzado a tablas (ADR-0005) |
| **Cifrado** | TLS 1.3 en tránsito; cifrado en reposo (PostgreSQL/volume); `destination_token` y `payload_raw` con cifrado a nivel de columna (`pgcrypto`) `DECIDIR` |
| **Auditoría** | `audit.log_entries` append-only con `correlation_id`/`request_id`; eventos #18–#24 y #38 consumidos por `audit` |
| **Lineage** | Cadena completa por transacción: solicitud API (`correlation_id`) → fila `deposit`/`withdrawal` → `provider_transaction` → `webhook_event` (causation) → `ledger_transactions.causation_id` → `LedgerPosted` → `audit.log_entries`. Reconstruible de extremo a extremo con un solo `correlation_id` |
| **Minimización** | El core no guarda datos de tarjeta, ni destinatarios completos (token + máscara), ni payloads innecesarios del proveedor |

---

## 10. Estado por fase: MOCK y bloqueos (remite a `X-blocked-to-live.md`)

### 10.1 Qué queda MOCK / PENDIENTE en Fase 1–5

| Componente | Estado Fase 1–5 | Qué existe | Verificación honesta |
|---|---|---|---|
| Servicio `payments` | `PENDIENTE` (Fase 6) | Diseño + rutas objetivo (`Q`) + eventos (#18–#24) | No hay código en Fase 1 |
| `PaymentProviderAdapter` + `PaymentMethodRegistry` + `ProviderWebhookReceiver` | `PENDIENTE` / diseño | Interfaces y contratos en este documento | Nada implementado aún |
| Adapter de depósito/retiro | `MOCK` (en Fase 6) | Simulador determinista: estados, `provider_ref`, webhooks firmados con secreto de prueba | **No** representa dinero real; etiquetado como simulado (`00-decisions` §6) |
| Webhooks reales | `MOCK` | Pipeline completo (firma, dedup, ventana, DLQ) probado con secreto de prueba | Sin tráfico de proveedor real |
| Métodos de pago (card/bank/crypto/local) | `DECIDIR` + `REQUIERE PROVEEDOR` | Tablas y registry | Sin rails contratados |
| Tokenización de tarjeta / alcance PCI | `REQUIERE PROVEEDOR` | Reglas §8 | Sin proveedor, sin alcance PCI definido |
| Screening AML de beneficiario | `MOCK` (manual) | Flujo manual auditado (`J` §6) | **Sin cobertura real** de sanciones/PEP |
| Motor de reglas de fraude | `PENDIENTE` | Esquema y umbrales como config versionada | Reglas iniciales por defecto, calibración pendiente |
| Reconciliación real | `MOCK` | Job y tabla `reconciliation_run` con datos simulados | Sin API de proveedor |
| Aprobaciones maker-checker | `PENDIENTE` (Fase 6/7) | Tabla `withdrawal_approval` + reglas | Backoffice de aprobación en Fase 7 (`admin`) |
| LIVE (`live_trading`) | Bloqueado por flag | Código deshabilitado por defecto | `false` hasta evidencia en `X-blocked-to-live.md` |

### 10.2 Qué bloquea la Fase 6 (entrada a dinero real)

| Bloqueo | Clase | Ref `X-blocked-to-live.md` |
|---|---|---|
| Contrato con PSP/adquirente + credenciales sandbox→live | `REQUIERE PROVEEDOR` | Sí |
| Rails bancarios y/o crypto (custodia, payouts) | `REQUIERE PROVEEDOR` | Sí |
| Secret manager/KMS para `webhook_secret_ref` | `REQUIERE PROVEEDOR` | Sí |
| Object storage para payloads/documentos | `REQUIERE PROVEEDOR` | Sí |
| Licencia/autorización regulatoria por jurisdicción para operar con dinero real | `REQUIERE LICENCIA` | Sí |
| Decisión de alcance PCI (SAQ/Level) según proveedor | `DECIDIR` | Sí |
| Screening sanciones/PEP con proveedor real | `REQUIERE PROVEEDOR` | Sí |
| Matriz de jurisdicción objetivo (entidad, monedas, límites) | `DECIDIR` | Sí |
| Políticas de disputa/chargeback y cooling-off de beneficiario | `DECIDIR` | Sí |
| Gate: `feature_flag live_trading=true` solo con checklist completo | gating | Sí |

**Regla de estado**: mientras exista cualquiera de los anteriores, los flujos de este documento operan en modo simulado y **no** pueden presentarse como operación real.

---

## 11. Decisiones pendientes

| Tema | Estado | Detalle |
|---|---|---|
| Eventos intermedios de depósito/retiro en catálogo P | `DECIDIR` | ¿Añadir `DepositValidationFailed`, `WithdrawalUnderReview`? (additive) |
| Ventana anti-replay y política de retries | `DECIDIR` | Inicio propuesto: ±300 s; 3 intentos backoff exponencial |
| Estado `REVERSED`/chargeback | `DECIDIR` | Requiere enmienda de catálogo + política de disputas |
| Reserva de fondos: tabla propia vs. convención de cuentas ledger | `DECIDIR` | Alternativas: cuenta `RESERVE` en ledger vs. hold en `wallet` |
| Cooling-off de beneficiario nuevo (duración) | `DECIDIR` | Jurisdicción-dependent |
| Cifrado a nivel de columna (`payload_raw`, `destination_token`) | `DECIDIR` | `pgcrypto` vs. application-level |
| Conciliación: frecuencia y auto-compensación | `DECIDIR` | Diaria + on-demand; auto-credit solo con regla explícita |
| Cuentas omnibus vs. segregadas PSP | `REQUIERE REGULACIÓN` | Hereda de `L` §10 |

---

*Fin del documento I-payments-architecture.md*
