# J — Arquitectura KYC/AML y Jurisdicciones

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `[PROJECT_NAME]` · Dominio: `[DOMAIN]` · Marca: `[BRAND_NAME]`

> **Regla de lectura**: diseño objetivo, no afirmación de implementación. Servicio `kyc` asignado a **Fase 6** (`00-decisions.md` §3), schema PostgreSQL propio `kyc` (ADR-0005, `O-database-strategy.md`); dominio `kyc-aml` con owner Compliance/KYC y steward CCO (`D-domain-map` #9). Eventos: catálogo `P-event-catalog.md` (#13–#15, consumidor de #1). Estados reales: `W-build-now.md` / `X-blocked-to-live.md`. **No se nombran proveedores concretos** (solo categorías) y **no se afirma acceso real a verificación de identidad, sanciones ni PEP** en ninguna fase hasta `REQUIERE PROVEEDOR` resuelto.

---

## 1. Principios inmutables

| # | Principio | Implementación |
|---|---|---|
| 1 | **Sin acoplamiento al proveedor** | Core solo con `KycProviderAdapter` y subinterfaces; el proveedor es un adapter intercambiable con failover; `provider_code` se guarda como cadena opaca |
| 2 | **Resultado normalizado** | Todo proveedor se traduce a `verified \| pending \| rejected \| requires_manual_review` (§3.3); el núcleo nunca interpreta payloads del proveedor |
| 3 | **Decisión sensible con humano en el bucle** | Las decisiones listadas en §9 exigen revisión humana trazable; la automatización solo en los casos de §9 marcados `auto-permitida` |
| 4 | **Prohibido hardcodear reglas regulatorias en el frontend** | El frontend consume únicamente la respuesta del Jurisdiction Rules Engine (§5); cualquier umbral/copia legal en cliente = defecto bloqueante |
| 5 | **PII = `RESTRICTED`** | Cifrado en reposo, minimización, acceso con registro, retención/eliminación por jurisdicción (§7) |
| 6 | **Sin ficción** | Sin proveedor real → adapter `MOCK` + flujo manual auditado; nunca afirmar cobertura de screening (§6) |
| 7 | **Trazabilidad total** | `correlation_id`/`causation_id` desde el formulario hasta la decisión; evidencia conservada; audit append-only |
| 8 | **DEMO vs LIVE** | La elegibilidad LIVE exige KYC aprobado + jurisdicción + suitability + `feature_flag live_trading` (hoy `false`) |

---

## 2. Flujo de onboarding por etapas

```text
REGISTER → EMAIL/PHONE VERIFICATION → PERSONAL DATA → COUNTRY/JURISDICTION → SUITABILITY
        → KYC → AML/SCREENING → ACCOUNT CREATION → DEMO/LIVE ELIGIBILITY
```

| # | Etapa | Datos recogidos | Validaciones | Evento emitido (catálogo P) | Decisión / destino | Fallos posibles |
|---|---|---|---|---|---|---|
| 1 | `REGISTER` | email, password, país declarado (opcional), consentimiento TOS/privacidad (`consent_record`) | formato email, política de password (Argon2id), rate limit por IP/dispositivo, anti-bot (`DECIDIR`), unicidad de email | **#1 `UserRegistered`** (`identity`) | Cuenta `identity` creada `unverified`; abre `kyc_case` en `draft` | email duplicado → 409; password débil → 422; rate limit → 429; dominio/dominio deshabilitado → 403 |
| 2 | `EMAIL/PHONE VERIFICATION` | OTP (hash + TTL), teléfono E.164 (opcional) | OTP: TTL corto, max intentos, single-use; formato E.164; proveedor de canal con retry | **#2 `UserEmailVerified`** (`identity`); teléfono: **sin evento en P** → `DECIDIR` (enmienda) | Canal verificado → habilita etapa 3; sin verificar → bloqueo de avance | OTP expirado; exceso de intentos (bloqueo temporal + alerta); proveedor de canal caído (retry/backoff); número/email ya usado en otra cuenta (señal de fraude → revisión) |
| 3 | `PERSONAL DATA` | nombre legal, fecha de nacimiento, dirección (normalizada), ocupación, teléfono | formato/longitud, normalización de dirección, edad mínima (`DECIDIR` por jurisdicción), coherencia interna | **Ninguno en P** → registrado en `kyc_case` + `audit` (`DECIDIR` enmienda) | `kyc_case` completo → etapa 4 | menor de edad → rechazo temprano; campos inválidos; incoherencia que saltará en documento (etapa 6) |
| 4 | `COUNTRY/JURISDICTION` | residencia, nacionalidad, país fiscal, declaración de tributación; IP del cliente **solo como señal** (nunca determinante; no confundir con GPS) | Cruce contra `jurisdiction_rule` vigente: ¿país soportado?, ¿producto permitido?, ¿documentación requerida? | Ninguno propio; si se cierra el caso por jurisdicción: **#15 `KycRejected`** (`kyc`) | Jurisdicción válida → fija entidad contractual, tier KYC y reglas de las etapas siguientes; no soportada → rechazo/registro `blocked` | jurisdicción prohibida; mismatch IP vs. residencia declarada (→ revisión manual); regla vigente ausente (fail-closed: bloquear, alertar) |
| 5 | `SUITABILITY` | experiencia con derivados, conocimiento, objetivos, tolerancia al riesgo, fuente de ingresos básica, propósito de la cuenta | scoring mínimo, respuestas coherentes entre sí, versión de cuestionario y disclaimer aceptados | Ninguno en P → evidencia en `kyc_case`/`kyc_check` | `suitable` → etapa 6; `unsuitable` → LIVE bloqueado (DEMO posible según jurisdicción); `incomplete` → info adicional | score insuficiente; respuestas contradictorias (→ revisión); questionnaire versionado no coincidente |
| 6 | `KYC` (identidad/documento/liveness) | documento de identidad (imagen/MRZ), selfie/liveness, comprobante de dirección (si el tier lo exige), número de documento (cifrado) | `KycProviderAdapter`: OCR/MRZ, vigencia, no alterado, comparación facial, calidad de imagen; reintento limitado | **#13 `KycSubmitted`** (`kyc`) al enviar; resultado normalizado por check | `verified` → etapa 7; `pending`/`requires_manual_review` → `in_review`; `rejected` → **#15 `KycRejected`** (`retry_allowed`) | imagen borrosa, documento expirado/dañado, liveness fallido, failover de proveedor (§3.4), proveedor caído → `pending` + reintento programado |
| 7 | `AML/SCREENING` | nombre, DOB, alias, países, PEP declarado, `source_of_funds`/`source_of_wealth` (según tier/jurisdicción) | screening sanciones/PEP/adverse media (§6), setup de monitorización transaccional, coherencia SOF/SOW vs. perfil | Ninguno propio; cierre de caso: **#14 `KycApproved`** o **#15 `KycRejected`** (`kyc`) | `clear` → aprobar; `possible_match` → revisión humana (maker-checker); `true_match` → rechazo + alerta Compliance | proveedor no disponible → **hold** (fail-closed) + §6 manual; falsos positivos; listas desactualizadas; SOF insuficiente |
| 8 | `ACCOUNT CREATION` | tipo de cuenta (demo/live), moneda, jurisdicción derivada, apalancamiento solicitado | KYC aprobado y vigente; `jurisdiction_rule` → productos/monedas permitidos; límites de tier | **#12 `AccountCreated`** (live) o **#16 `DemoAccountCreated`** (`accounts`) | Cuenta creada; `wallet` inicial; plan de features por jurisdicción | KYC expirado; jurisdicción no permite el tipo; moneda no soportada; ya existe cuenta activa equivalente |
| 9 | `DEMO/LIVE ELIGIBILITY` | composición de todo lo anterior + flags | KYC tier + suitability + jurisdicción + contratos + licencia + `feature_flag live_trading` | Ninguno nuevo (gating); cambios de elegibilidad auditados | `DEMO` habilitado (si jurisdicción lo permite); `LIVE` **solo** con checklist completo en `X-blocked-to-live.md` | intento LIVE con flag off → `403 FEATURE_DISABLED`; sin KYC → LIVE denegado; KYC expirado → degradación a `expired` (§4) |

**Reglas transversales**: cada etapa es una fila en `kyc_case`/`kyc_check` con `correlation_id` único; el avance es monotónico salvo `requeue`; ninguna etapa se salta por decisión del cliente; los fallos de etapa nunca pierden evidencia ya subida.

---

## 3. Interfaces abstractas `KycProviderAdapter`

### 3.1 Estructura

```python
# services/kyc/app/providers/base.py  (Python 3.13, Pydantic v2)
class KycProviderAdapter(Protocol):
    provider_code: str  # opaco, no se expone marca al core
    capabilities: frozenset[CheckType]


class IdentityVerificationAdapter(Protocol):
    async def verify(self, req: IdentityVerifyRequest) -> NormalizedCheckResult: ...


class DocumentVerificationAdapter(Protocol):
    async def submit_document(self, doc: DocumentSubmission) -> NormalizedCheckResult: ...
    async def get_result(self, provider_ref: str) -> NormalizedCheckResult: ...


class LivenessAdapter(Protocol):
    async def start_challenge(self, session: LivenessSession) -> LivenessChallenge: ...
    async def submit_result(self, result: LivenessSubmission) -> NormalizedCheckResult: ...


class PepScreeningAdapter(Protocol):
    async def screen(self, subject: ScreeningSubject) -> list[ScreeningMatch]: ...


class SanctionsScreeningAdapter(Protocol):
    async def screen(self, subject: ScreeningSubject) -> list[ScreeningMatch]: ...


class AddressVerificationAdapter(Protocol):
    async def verify(self, address: AddressSubmission) -> NormalizedCheckResult: ...


class SourceOfFundsAdapter(Protocol):
    async def assess(self, submission: SofSubmission) -> NormalizedCheckResult: ...


class SourceOfWealthAdapter(Protocol):
    async def assess(self, submission: SowSubmission) -> NormalizedCheckResult: ...


class KytAdapter(Protocol):  # crypto: travel-rule / wallet screening
    async def screen_wallet(self, address: str, chain: str) -> NormalizedCheckResult: ...
```

### 3.2 Modelo interno normalizado (único que ve el núcleo)

```python
class NormalizedCheckResult(BaseModel):
    status: Literal["verified", "pending", "rejected", "requires_manual_review"]
    score: Decimal | None  # 0..1, si el proveedor lo da
    reason_codes: list[str]  # códigos propios, normalizados
    provider_code: str  # opaco, para auditoría
    provider_ref: str | None
    raw_payload_ref: str | None  # pointer a object storage (REQUIERE PROVEEDOR), nunca inline en logs
    checked_at: datetime  # UTC
    expires_at: datetime | None  # vigencia del resultado
    failover_of: str | None  # id del check anterior si hubo failover
```

| `CheckType` | Subinterface | Uso |
|---|---|---|
| `identity` | `IdentityVerificationAdapter` | verificación de identidad por datos |
| `document` | `DocumentVerificationAdapter` | documento oficial, MRZ/OCR |
| `liveness` | `LivenessAdapter` | selfie + detección de vida |
| `pep` | `PepScreeningAdapter` | PEP/funcionarios |
| `sanctions` | `SanctionsScreeningAdapter` | listas de sanciones |
| `address` | `AddressVerificationAdapter` | comprobante de domicilio |
| `source_of_funds` | `SourceOfFundsAdapter` | procedencia de fondos |
| `source_of_wealth` | `SourceOfWealthAdapter` | origen de riqueza |
| `kyt` | `KytAdapter` | movimientos/wallets cripto |

### 3.3 Multi-proveedor: failover, circuit breaker, normalización

| Mecanismo | Especificación |
|---|---|
| **Routing** | Tabla de preferencias `check_type × jurisdiction × tier` → lista ordenada de `provider_code`; sin proveedor elegible → `pending` + alerta (fail-closed, nunca auto-verificar) |
| **Failover** | Solo ante errores `retryable`/`PROVIDER_UNAVAILABLE`/timeout; se registra `failover_of`; el resultado del proveedor secundario no pisa el primario (ambos conservados) |
| **Circuit breaker** | Por `provider_code`: umbral de fallos → `open` (cooldown) → `half-open` (sondeo) → `closed`; parámetros `DECIDIR`; métricas en Prometheus |
| **Timeout/retries** | Timeout por operación + backoff exponencial con jitter; tope de intentos; sin retries para resultados `rejected` (no es error) |
| **Normalización** | Cada adapter traduce su taxonomía al modelo interno; mapeo documentado por adapter y versionado; `score` del proveedor nunca se usa sin umbral propio versionado |
| **Aislamiento** | El núcleo no importa SDKs; los tipos del proveedor no salen del paquete adapter; la respuesta al cliente nunca expone `provider_code` salvo en admin auditado |
| **Observabilidad** | Latencia, tasa de failover, tasa de `requires_manual_review` por proveedor → alimenta el routing |
| **Modo** | Mismo pipeline con adapter `MOCK` determinista en Fase 1–6 (`X-blocked-to-live.md`) |

---

## 4. Estados del caso KYC y revisión manual

| Estado | Significado | Quién lo transiciona | Evento P |
|---|---|---|---|
| `draft` | Caso abierto, etapas 3–5 en curso | usuario (vía API) | — |
| `submitted` | Enviado a proveedor(es) | `kyc` service | **#13 `KycSubmitted`** |
| `in_review` | Espera revisión humana (hit, baja calidad, discrepancia, SOF) | motor/adapter (`requires_manual_review`) | — |
| `approved` | Verificado; tier y `expires_at` asignados | sistema (auto) o revisor+checker | **#14 `KycApproved`** |
| `rejected` | No verificado; `reason` + `retry_allowed` | revisor (o hit confirmado) | **#15 `KycRejected`** |
| `expired` | Vigencia superada (`expires_at < now`) | job programado | — (requiere enmienda P, `DECIDIR`) |
| `requeue` | Reapertura tras expiración, cambio de datos o nueva evidencia | usuario/admin con validaciones | vuelve a `submitted` → #13 |

**Transiciones válidas**: `draft → submitted`; `submitted → in_review | approved | rejected`; `in_review → approved | rejected | submitted` (más evidencia); `approved → expired`; `expired → requeue → submitted`; `rejected → requeue → submitted` (solo si `retry_allowed`); `approved → rejected` solo por re-review documentado (ej. hit posterior) con doble aprobación. `approved/rejected` son terminales salvo los caminos anteriores.

### 4.1 Revisión humana (maker-checker), SLA, evidencia, trazabilidad

| Elemento | Regla |
|---|---|
| **Maker-checker** | El revisor que resuelve (`maker`) no puede ser el que aprueba la decisión sensible (`checker`) cuando: alta de tier, `true_match` PEP/sanciones, rechazo apelado o monto/cobertura alta (§9). Ambos identidades de operador reales, jamás service accounts compartidas |
| **SLA interno** | decisión automática objetivo < 3 min; revisión manual objetivo < 24 h (gate de Fase 6, `T-roadmap`); `sla_due_at` en cada `in_review`; escalado automático al vencer (`DECIDIR` umbral) |
| **Evidencia** | Se conserva todo: imágenes/documentos originales (cifrados), `raw_payload_ref` del proveedor, respuestas normalizadas, decisión y `reason`; nada se sobrescribe (append-only) |
| **Trazabilidad** | Cada transición → fila + `audit.log_entries` (actor, rol, antes/después, motivo, `correlation_id`); decisiones sensibles → evento #14/#15 con `approved_by`/`reason` |
| **Fail-closed** | Si el motor, el proveedor o la cola fallan en una etapa sensible → no se aprueba; se queda en `in_review` con alerta |
| **Conflictos** | Decisión automática + revisor en desacuerdo → prevalece la revisión humana, ambas registradas |

---

## 5. Jurisdiction Rules Engine (motor de reglas de jurisdicción)

### 5.1 Rol y regla explícita

Motor **centralizado, versionado y auditable** (propiedad del dominio `jurisdictions`, `D-domain-map` #18; almacenamiento mínimo en schema `kyc` con opción de extracción a servicio propio). Es la **única** fuente de verdad de reglas regulatorias.

> **Regla prohibitoria**: está prohibido hardcodear reglas regulatorias (umbrales, apalancamientos, listas de productos, disclosures, requisitos KYC, límites) en el frontend o en código de negocio fuera del motor. El frontend y cualquier servicio **solo consumen la respuesta** del motor. Toda regla vive versionada en `jurisdiction_rule` con autor, vigencia y diff.

```python
class JurisdictionRulesEngine(Protocol):
    async def evaluate(
        self, *, jurisdiction: str, subject: SubjectRef, feature: str, as_of: datetime | None = None
    ) -> RuleDecision: ...
    async def explain(self, evaluation_id: str) -> RuleExplanation: ...  # trazabilidad reproducible


class RuleDecision(BaseModel):
    allowed: bool
    entity_contractual: str | None
    products_allowed: list[str]
    max_leverage: Decimal | None
    payment_methods_allowed: list[str]
    disclosures: list[str]
    required_documents: list[str]
    kyc_required: str | None  # tier mínimo
    restrictions: list[str]
    investor_protections: list[str]
    limits: dict[str, Decimal]
    languages: list[str]
    currencies: list[str]
    features_enabled: list[str]
    rule_versions: dict[str, int]  # versión exacta usada por clave
    reason_codes: list[str]
    evaluation_id: str  # id para reproducir la decisión
```

### 5.2 Determina (lista mínima)

Entidad contractual · productos permitidos · apalancamiento máximo · métodos de pago · disclosures · documentación obligatoria · nivel KYC requerido · restricciones de uso · protecciones al inversor · límites (depósito/retiro/exposición) · idiomas · monedas · features habilitadas (incluida elegibilidad LIVE).

### 5.3 Governance de `jurisdiction_rule`

| Atributo | Descripción |
|---|---|
| `version` | entero incremental por `rule_key` + `jurisdiction` |
| `valid_from` / `valid_to` | vigencia temporal; evaluaciones históricas se reproducen con la versión vigente en ese instante (`as_of`) |
| `author` / `approved_by` | persona autora y aprobadora (maker-checker); service accounts prohibidas |
| `diff_from_prev` | diff JSON contra la versión anterior |
| `change_reason` + `source_ref` | motivo y referencia al memo/fuente legal (no se afirma cumplimiento; fuente documentada) |
| `status` | `draft → active → retired` (nunca `UPDATE` sobre activa: nueva versión) |
| Evaluación auditada | Cada `evaluate` persiste `evaluation_id` + `rule_versions` → una decisión de hace 6 meses es reproducible |

**Fail-closed**: jurisdicción sin regla vigente → `allowed=false` + alerta. **Invalidación de cache**: por `rule_version`, nunca por TTL ciego.

---

## 6. Screening de sanciones/PEP — `REQUIERE PROVEEDOR`

| Afirmación prohibida | En su lugar |
|---|---|
| "Cobertura de sanciones/PEP" | "**Sin cobertura real verificada**: adapter `MOCK` + lista cargada manualmente; screening efectivo solo con proveedor contratado" |
| "Cumplimiento AML verificado" | Estado `MOCK`/`PENDIENTE` en `W-build-now.md` y bloqueo en `X-blocked-to-live.md` |

**Diseño mientras está bloqueado (Fase 1–5 y hasta proveedor):**

| Pieza | Detalle |
|---|---|
| Adapter | `SanctionsScreeningAdapter`/`PepScreeningAdapter` **MOCK**: matching determinista contra una lista local |
| Carga de lista | Operador autorizado sube archivo → se calcula `sha256`, se registra `list_source`, `list_version`, `uploaded_by`, `uploaded_at`, `approved_by` en `screening_result`/auditoría; sin hash y aprobación, la lista no se usa |
| Matching | Normalización de nombre (mayúsculas, transliteración básica, orden), coincidencia exacta + difusa (`DECIDIR` umbral); resultado: `no_match \| possible_match \| true_match` |
| Flujo manual | `possible_match` → cola `in_review` con SLA; disposición humana (`false_positive`/`true_match`) con `reviewed_by`, `reviewed_at`, `reason`; `true_match` → bloqueo + alerta Compliance + posible #15 `KycRejected` |
| Transparencia | UI/backoffice muestra explícitamente: "lista manual, cobertura no verificada, fecha de la lista" |
| Ongoing | Re-screening periódico y ante actualización de lista (`DECIDIR` frecuencia); hit posterior sobre cuenta aprobada → `approved → rejected` con doble aprobación (§4) |
| Cuando haya proveedor | El mismo pipeline con adapter real; el flujo manual queda como fallback con la misma auditoría |

---

## 7. Privacidad y PII

| Dimensión | Decisión |
|---|---|
| **Clasificación** | Todo dato de este documento = **`RESTRICTED`** (PII máximo: identidad, documentos, screening, IP/dispositivo) |
| **Cifrado en reposo** | PostgreSQL/volume encryption + cifrado de columna para nº de documento y campos directamente identificables (`pgcrypto` o application-level, `DECIDIR`); TLS 1.3 en tránsito; object storage cifrado (`REQUIERE PROVEEDOR`) |
| **Minimización** | Recolectar solo lo que exija el tier/jurisdicción (dictado por `jurisdiction_rule.required_documents`); máscara en UI (`••••`), redacción en logs, no enviar PII a métricas/trazas (OpenTelemetry: solo IDs) |
| **Retención/eliminación** | Duración por jurisdicción → **`DECIDIR jurisdicción objetivo`** (no se afirma plazo ni cumplimiento legal concreto: GDPR/CCPA/etc. **sin determinar**). Mecanismo previsto: `retention_until` por fila → job de expiración → anonimización o borrado, con `legal_hold` que suspende el borrado |
| **Exportación/borrado bajo solicitud** | Flujo: solicitud → verificación de identidad del solicitante → comprobación de `legal_hold` y de obligaciones contables (los asientos del ledger **nunca** se borran, `L` §9) → exportación/anonimización de PII de KYC → registro de la propia operación de borrado (quién, cuándo, alcance, base). **No** se afirma cumplimiento normativo hasta `DECIDIR` jurisdicción |
| **Acceso** | RBAC: solo Compliance/KYC y revisores asignados; cada lectura de documento/resultado registrada en `audit.log_entries`; sin acceso de soporte genérico; sesiones step-up MFA para acciones sensibles |
| **Consentimiento** | `consent_record` con versión del texto, `granted/revoked_at`, IP hasheada, `evidence_ref`; revocación propagada a consumidores vía eventos |
| **Proveniencia de IP/device** | Solo como señal de riesgo declarada como tal; **nunca** presentar GEO-IP aproximada como geolocalización GPS; sin fingerprinting encubierto |
| **Supply chain** | Logs y backups heredan clasificación `RESTRICTED`; retención de backups `DECIDIR` |

---

## 8. Modelo de datos previsto (schema `kyc`)

| Tabla | Columnas clave | Clasificación |
|---|---|---|
| `kyc_case` | `id` (UUIDv7), `user_id`, `account_id` (NULL hasta etapa 8), `jurisdiction`, `stage` (onboarding etapa 1–9), `state` (draft/submitted/in_review/approved/rejected/expired/requeue), `tier_requested`, `tier_granted`, `risk_score`, `risk_level`, `suitability_result`, `decision`, `decision_reason`, `decided_by` (system/user id), `decision_mode` (auto/manual), `rule_evaluation_id`, `sla_due_at`, `submitted_at`, `decided_at`, `expires_at`, `requeue_reason`, `correlation_id`, `created_at`, `updated_at` | **RESTRICTED** |
| `kyc_check` | `id`, `kyc_case_id FK`, `check_type` (identity/document/liveness/pep/sanctions/address/source_of_funds/source_of_wealth/kyt), `provider_code`, `provider_ref`, `normalized_status` (verified/pending/rejected/requires_manual_review), `score`, `reason_codes`, `raw_payload_ref`, `attempt`, `failover_of_check_id`, `rule_id`, `rule_version`, `checked_at`, `expires_at`, `created_at` | **RESTRICTED** |
| `kyc_document` | `id`, `kyc_case_id FK`, `doc_type`, `issuing_country`, `doc_number_encrypted`, `doc_number_last4`, `file_ref` (object storage `REQUIERE PROVEEDOR`), `file_hash` (SHA-256), `encryption_key_ref`, `redacted`, `uploaded_at`, `verified_at`, `expires_at`, `retention_until`, `legal_hold` | **RESTRICTED** |
| `screening_result` | `id`, `subject_type` (user/beneficiary), `subject_id`, `check_type` (sanctions/pep/adverse_media/internal_list), `list_source` (provider | manual), `list_version`, `list_hash`, `match_score`, `match_fields`, `disposition` (no_match/possible_match/true_match), `disposition_reason`, `reviewed_by`, `reviewed_at`, `provider_code`, `provider_ref`, `created_at` | **RESTRICTED** |
| `jurisdiction_rule` | `id`, `jurisdiction`, `rule_key`, `version`, `status` (draft/active/retired), `payload` (productos, apalancamiento, métodos, disclosures, docs, KYC tier, restricciones, protecciones, límites, idiomas, monedas, features), `valid_from`, `valid_to`, `author`, `approved_by`, `diff_from_prev`, `change_reason`, `source_ref`, `created_at`, `UNIQUE (jurisdiction, rule_key, version)` | **CONFIDENTIAL** (config regulatoria sin PII; coherente con `D-domain-map` jurisdictions) |
| `consent_record` | `id`, `user_id`, `consent_type` (terms/privacy/marketing/jurisdictional_disclosure), `document_version`, `granted`, `granted_at`, `revoked_at`, `jurisdiction`, `ip_hash`, `user_agent`, `evidence_ref`, `created_at` | **CONFIDENTIAL** (evidencia legal; IP solo hasheada) |

Índices críticos: `kyc_case (user_id, state)`, `kyc_case (state, sla_due_at) WHERE state='in_review'` (cola de revisión), `kyc_check (kyc_case_id, check_type)`, `screening_result (subject_id, check_type, created_at DESC)`, `jurisdiction_rule (jurisdiction, rule_key, status, valid_from)`.

**Integraciones (sin joins entre schemas)**: `kyc → identity` (datos de usuario), `kyc → accounts` (#12/#14/#15), `kyc → payments` (gate de retiros vía estado KYC), `kyc → audit` (consumidor de eventos y productor de #13–#15).

---

## 9. Decisiones automáticas sensibles → revisión humana y trazabilidad

| # | Decisión automática | Sensibilidad | ¿Revisión humana? | Trazabilidad mínima |
|---|---|---|---|---|
| 1 | Auto-aprobación KYC por score de proveedor | Identidad / acceso a cuenta | Solo si tier medio-alto o score en zona gris → **sí**; LOW+score alto → auto-permitida con muestreo (`DECIDIR` %) | `kyc_check` + `decision_mode=auto` + `rule_id/version` + `evaluation_id` |
| 2 | Rechazo automático por documento/liveness fallido | Acceso al servicio | **Sí** si el usuario apela o reintenta; primer rechazo auto-permitida con evidencia | intentos, `reason_codes`, `raw_payload_ref` |
| 3 | Disposición de coincidencia sanciones/PEP | Legal / bloqueo de cuenta | **Sí, siempre** (maker-checker para `true_match`) | `screening_result` completo + `reviewed_by/at` |
| 4 | Bloqueo por jurisdicción no soportada | Acceso / contractual | **Sí** para excepciones (cambio de residencia acreditado) | `jurisdiction_rule` versión + `evaluation_id` |
| 5 | Rechazo por suitability insuficiente (LIVE) | Elegibilidad de producto | **Sí** para recurso/reevaluación | versión del cuestionario + scoring + revisor |
| 6 | `source_of_funds` insuficiente/vagos | AML | **Sí** (dos revisores si rechazo) | SOF/SOW + decisión + evidencia |
| 7 | Asignación de tier KYC/límites por jurisdicción | Dinero / límites | **Sí** para ampliación de tier | `rule_versions` + `evaluation_id` + aprobador |
| 8 | Caducidad automática de KYC (`expired`) | Continuidad de cuenta | **Sí** si hay reclamación; degradación automática de acceso auto-permitida | job + `expires_at` + notificación |
| 9 | Hold de depósito/retiro por motor de reglas de fraude | Dinero | **Sí** para liberar el hold (nunca auto-liberar `HIGH/CRITICAL`) | `risk_level`, `rule_id/version`, hash de entradas, aprobador (`I` §7) |
| 10 | Beneficiario nuevo / cambio de destino | Fraude / take-over | **Sí**, siempre primer uso | `beneficiary_first_use`, verificación de titularidad, maker-checker (`I` §7) |
| 11 | Screening KYT de wallet cripto | Dinero / travel rule | **Sí** ante `possible_match` | `kyc_check` tipo `kyt` + disposición |
| 12 | Elegibilidad LIVE (flag + checklist) | Regulatorio | **Sí** (legal/compliance firma el gating) | checklist en `X-blocked-to-live.md` + flag auditado |

**Regla general**: si una decisión automática **niega, restringe o bloquea** al usuario, debe ser reversible por revisión humana, con `reason` legible, y quedar registrada con actor, timestamp, versión de regla y evidencia. Ninguna decisión sensible se ejecuta con motor o proveedor en fallo (fail-closed).

---

## 10. Estado por fase y bloqueos (remite a `X-blocked-to-live.md`)

| Componente | Fase 1–5 | Bloqueo para real |
|---|---|---|
| Servicio `kyc` + pipeline de etapas | `PENDIENTE` (Fase 6) | — |
| `KycProviderAdapter` + subinterfaces | diseño (`IMPLEMENTADO` como documento) | — |
| Adapters de identidad/documento/liveness | `MOCK` determinista | `REQUIERE PROVEEDOR` |
| Screening sanciones/PEP/adverse media | `MOCK` + lista manual auditada (§6) | `REQUIERE PROVEEDOR` |
| KYT / travel rule | `MOCK` | `REQUIERE PROVEEDOR` |
| Address/SOF/SOW | `PENDIENTE`/`MOCK` | `REQUIERE PROVEEDOR` (según tier) |
| Object storage para documentos | placeholder | `REQUIERE PROVEEDOR` |
| Jurisdiction Rules Engine (tabla + motor) | `PENDIENTE` (esquema diseñado) | Matriz de jurisdicción objetivo = `DECIDIR` |
| Retención/exportación/borrado PII | mecanismo diseñado | Plazo y obligaciones = `DECIDIR` jurisdicción objetivo; **sin** afirmación de cumplimiento |
| Cifrado de columna / KMS | `DECIDIR` | `REQUIERE PROVEEDOR` (KMS/Vault) |
| Onboarding LIVE | bloqueado por flag + KYC real | `REQUIERE LICENCIA` + checklist `X-blocked-to-live.md` |

---

## 11. Decisiones pendientes

| Tema | Estado | Detalle |
|---|---|---|
| Jurisdicción(es) objetivo(s) y entidad contractual | `DECIDIR` | Condiciona reglas, retención, disclosures |
| Plazos de retención/eliminación PII por jurisdicción | `DECIDIR` | Sin afirmar GDPR u otra norma concreta |
| Eventos de onboarding intermedios en catálogo P | `DECIDIR` | ¿Etapa completada / `KycExpired`? (additive en `P-event-catalog.md`) |
| Umbrales de score para auto-aprobación y % de muestreo | `DECIDIR` | Calibración con datos reales |
| SLA y escalado de `in_review` | `DECIDIR` | Objetivo <24 h; definir escalado |
| Umbral de matching difuso en modo manual | `DECIDIR` | Tasa de falsos positivos aceptable |
| Servicio `jurisdictions` propio vs. esquema en `kyc` | `DECIDIR` | Criterios ADR-0002 |
| MFA/passkeys en etapas sensibles del onboarding | `PENDIENTE` | TOTP hoy; WebAuthn `PENDIENTE` (`00-decisions` §7) |

---

*Fin del documento J-kyc-aml-architecture.md*
