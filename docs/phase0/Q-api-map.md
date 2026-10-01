# Q — Mapa de API REST `/api/v1/` (API Map)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `MonedasAR` · Dominio: `[DOMAIN]` · Marca: `MonedasAR`

> **Regla de lectura**: este documento es el **mapa de rutas objetivo**, no una afirmación de implementación. La columna **Fase** indica la fase planeada (1–9). El estado real por componente (`IMPLEMENTADO` / `PARCIAL` / `MOCK` / `PENDIENTE` / `REQUIERE PROVEEDOR` / `REQUIERE LICENCIA`) se declara únicamente en `W-build-now.md` y `X-blocked-to-live.md`. Fase 1 real = `gateway`, `identity`, `audit`; todo lo demás está diseñado para fases posteriores.
> Complemento: streaming en `R-websocket-map.md` (`/ws/v1`). Eventos de negocio: `P-event-catalog.md`. Decisiones canónicas: `00-decisions.md`.

---

## 1. Convenciones Globales

### 1.1 Prefijo, superficie y exposición

| Regla | Detalle |
|---|---|
| Prefijo público | `/api/v1/` servido **exclusivamente** por `gateway` (routing, validación JWT, rate limit, `X-Request-Id`, headers de seguridad) |
| Prefijo interno | `/internal/v1/` **nunca** enrutado por el gateway; bloqueado en edge (404/403) y accesible solo en red de servicio |
| Versionado en path | `/api/v{major}/{recurso}`; el major es el único artefacto que cambia por breaking change |
| IDs públicos | UUIDv7 (o aleatorio no secuencial) en toda entidad expuesta; prohibido autoincremento expuesto |
| Tiempo | Todo timestamp en UTC RFC 3339 con precisión ≥ milisegundos (`2026-09-27T14:32:10.123Z`) |
| Dinero | Nunca `float`: cadenas decimales (`"1234.56789012"`) + `currency` ISO 4217; `amount_minor` cuando la moneda lo permita |
| Modo | Respuesta informativa `mode: "DEMO" | "LIVE"`; `LIVE` bloqueado por `feature_flag live_trading=false` (00-decisions §6) |
| Content-Type | `application/json` salvo `application/problem+json` en errores y formatos de export (`text/csv`, `application/pdf`) |
| Tamaño de cuerpo | Máx. 1 MiB en escrituras estándar; 8 MiB en subida de documentos KYC; exceder → `413` problem+json |

### 1.2 Versionado y evolución (sin breaking changes silenciosos)

| Mecanismo | Regla |
|---|---|
| Versionado mayor | `/api/v2` se crea solo ante breaking change. **Nunca** se reutiliza `/api/v1` para cambiar semántica de un recurso existente |
| Cambio **no** breaking (minor) | Añadir campo `optional` con default; añadir endpoint; añadir valor a enum **solo si** los clientes toleran valores desconocidos (regla obligatoria documentada en el SDK); ampliar límites; añadir query param opcional |
| Cambio **breaking** (major) | Renombrar/eliminar campo; cambiar tipo/unidad; hacer obligatorio un campo opcional; cambiar semántica de un status code; eliminar endpoint; restringir scopes; cambiar reglas de idempotencia |
| Bloqueo en CI | Diff de `openapi.yaml` contra la rama base: cualquier breaking detectado **falla el pipeline** salvo que el diff incluya bump de major y entrada en el changelog de deprecación |
| Doble escritura | Durante solapamiento (≥ 90 días) los servicios aceptan ambas versiones y, si aplica, responden campo nuevo + campo antiguo marcado `deprecated: true` |
| Cabeceras de deprecación | Ruta deprecada responde siempre `Deprecation: @<date>` (Internet-Draft HTTP API) y `Sunset: <HTTP-date>` (RFC 8594) con ≥ **180 días** de aviso; `Link: rel="successor-version"` cuando exista `/api/v2` |
| Comunicación | Entrada en changelog + `GET /api/v1/version` expone `deprecations[]` con ruta, fecha `Sunset` y sucesora |
| APIs internas | Versionadas también (`/internal/v1/`); los consumidores internos se actualizan **antes** de deprecar la versión pública equivalente |

> **Garantía central**: no existen breaking changes silenciosos — todo rompimiento exige (1) major nuevo en path, (2) diff de contrato aprobado en CI, (3) `Sunset` publicado, (4) ventana de solapamiento.

### 1.3 Errores — RFC 9457 (`problem+json`)

Todo error de `4xx/5xx` responde `Content-Type: application/problem+json`:

```json
{
  "type": "urn:platform:problem:idempotency-key-reuse",
  "title": "Idempotency-Key reutilizada con cuerpo distinto",
  "status": 409,
  "detail": "La clave fue usada 2026-09-27T14:32:10Z con un payload distinto.",
  "instance": "/api/v1/orders",
  "code": "IDEMPOTENCY_KEY_REUSE",
  "request_id": "0192f7c0-7b3a-7f2a-8c4e-1a2b3c4d5e6f",
  "correlation_id": "0192f7c0-7b3a-7f2a-8c4e-1a2b3c4d5e6f",
  "errors": [{ "field": "amount", "issue": "must be a decimal string", "value": "10,5" }],
  "timestamp": "2026-09-27T14:32:10.123Z"
}
```

| Campo | Obligatorio | Nota |
|---|---|---|
| `type` | Sí | URN estable por clase de error; es el **contrato** que usan los clientes (no parsear `title`) |
| `code` | Sí | Enum corto en `SCREAMING_SNAKE_CASE` versionable de forma independiente |
| `request_id` / `correlation_id` | Sí | Trazabilidad extremo a extremo (00-decisions §7); también van en cabecera `X-Request-Id` |
| `errors[]` | Solo `422` | Errores de validación campo a campo (Pydantic → problema) |

Catálogo mínimo de `type`/`code` (crece de forma aditiva):

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `VALIDATION_ERROR` / `MALFORMED_JSON` | Cuerpo o query inválidos |
| 401 | `UNAUTHENTICATED` / `TOKEN_EXPIRED` / `TOKEN_INVALID` | Sin/ con JWT inválido o caducado |
| 403 | `INSUFFICIENT_SCOPE` / `TOPIC_FORBIDDEN` / `MODE_DISABLED` | Scope insuficiente, recurso ajeno, `live_trading=false` |
| 404 | `NOT_FOUND` | Recurso inexistente o ajeno al sujeto (misma respuesta: anti-enumeración) |
| 409 | `IDEMPOTENCY_KEY_REUSE` / `IDEMPOTENCY_IN_PROGRESS` / `STATE_CONFLICT` | Conflicto de idempotencia o máquina de estados |
| 413 | `PAYLOAD_TOO_LARGE` | Cuerpo excede límite |
| 422 | `BUSINESS_RULE_VIOLATION` | Regla de negocio (margen insuficiente, moneda no permitida, jurisdicción bloqueada) |
| 423 | `RESOURCE_LOCKED` | Recurso en proceso (ej. retiro en revisión) |
| 429 | `RATE_LIMITED` / `QUOTA_EXCEEDED` | Tasa o cuota agotadas → `Retry-After` |
| 500 | `INTERNAL_ERROR` | Error no controlado (sin detalle interno al cliente) |
| 503 | `SERVICE_UNAVAILABLE` / `DEPENDENCY_UNAVAILABLE` | Caída de dependencia; con `Retry-After` |
| 504 | `DEPENDENCY_TIMEOUT` | Timeout aguas abajo |

### 1.4 Paginación por cursor (obligatoria en colecciones)

| Regla | Detalle |
|---|---|
| Params | `?limit=` (default 25, máx 100 salvo indicación) y `?cursor=` (opaaco, firmado/opaco del servidor) |
| Respuesta | `{ "data": [...], "page": { "next_cursor": "…", "prev_cursor": "…", "has_more": true, "limit": 25 } }` |
| Estabilidad | Cursor sobre orden determinista `(created_at DESC, id DESC)`; **sin** offset: inmune a inserts concurrentes (BUILD-022) |
| Fin | `next_cursor = null` + `has_more = false`; cursor caducado → `400 INVALID_CURSOR` |
| Prohibido | `?page=`/`?offset=` en recursos financieros (desplazamiento = duplicados/omisiones) |
| Orden | `?sort=-created_at` (prefijo `-` = descendente); solo campos indexados del recurso |

### 1.5 Filtros

| Sintaxis | Ejemplo | Soporte |
|---|---|---|
| Igualdad simple | `?status=open&currency=USD` | Todas las colecciones |
| Operadores sufijos | `?created_at_gte=…&created_at_lt=…`, `?amount_gte=10.00` | `_gte _gt _lte _lt _ne` |
| Lista | `?status=in:open,filled` | `_in` |
| Búsqueda | `?q=` (solo campos indexados permitidos; nunca PII parcial sin mínimo 3 caracteres) | listados admin |
| Rango obligatorio | Endpoints financieros con volumen alto exigen `from`/`to` (máx 90 días por consulta) | ledger, transactions, trades, audit |
| Validación | Filtro no soportado → `400 VALIDATION_ERROR` (nunca ignorarse en silencio) | Todas |

### 1.6 Cabeceras

| Cabecera | Dirección | Regla |
|---|---|---|
| `Authorization: Bearer <jwt>` | req | JWT de acceso **≤ 15 min** (00-decisions §7); validado en gateway (firma/exp/`aud`/`iss`) con JWKS de `identity` |
| `Authorization: Bearer <api_key>` | req | API keys de plataforma (cliente programático); scope limitado; con `ip_whitelist` opcional |
| `Idempotency-Key` | req | **Obligatorio** en todos los `POST` de flujos financieros (§1.7); UUIDv7; alcance = (ruta, sujeto) |
| `X-Request-Id` | req/resp | Acepta id del cliente si es UUID; si no, el gateway genera uno y lo devuelve siempre |
| `X-Correlation-Id` | req/resp | Cadena de trace end-to-end; se propaga a eventos (`correlation_id`) y audit |
| `Idempotent-Replay: true` | resp | Indica que la respuesta fue reproducida desde el registro de idempotencia |
| `RateLimit-Limit` / `RateLimit-Remaining` / `RateLimit-Reset` | resp | Cuota, restante y ventana (cabeceras estándar IETF en curso); siempre en respuestas de rutas con límite |
| `Retry-After` | resp `429/503` | Segundos hasta reintentar |
| `Deprecation` / `Sunset` | resp | Solo en rutas deprecadas (§1.2) |
| `Location` | resp `201`/`202` | URI del recurso creado o del job |
| Seguridad | resp | `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` en datos sensibles, `Content-Security-Policy` en HTML |

### 1.7 Autenticación, scopes y autorización

**Scope base (OAuth2-style, mínimo necesario):**

| Scope | Significa | Ejemplos de rutas |
|---|---|---|
| `read` | Lectura de datos propios o públicos | `GET /accounts`, `GET /orders`, `GET /ledger/statements` |
| `trade` | Operar órdenes/posiciones (dinero en riesgo de mercado) | `POST /orders`, `POST /positions/{id}/close` |
| `payments` | Mover dinero fuera/entre cuentas (depósitos, retiros, transferencias) | `POST /withdrawals`, `POST /wallet/transfers` |
| `admin` | Backoffice: acciones sobre terceros y configuración | `GET /admin/users`, `POST /admin/kyc/{id}/approve` |

Reglas de autorización:

1. **Mínima autoridad**: cada ruta declara el scope mínimo; los endpoints `GET` de recursos propios exigen sesión válida + `read`.
2. **Sesión vs API key**: las operaciones *self-service* de identidad (MFA, password, sesiones, API keys, perfil) exigen **sesión de usuario** (no API key) y **step-up MFA** para operaciones sensibles; las API keys solo cubren `read`/`trade`/`payments` + recursos que su creador pueda ver.
3. **Alcance de objeto (BOLA)**: todo recurso se filtra por `subject_id`/`account_id` del token; recurso ajeno o inexistente → misma respuesta `404 NOT_FOUND`. Cruzar cuentas requiere `admin` **y** parámetro de cuenta explícito, auditado.
4. **RBAC + scope**: scope habilita la categoría; el rol (`user`, `ops`, `compliance`, `auditor`, `superadmin`) habilita la acción concreta (identity, Fase 1).
5. **MFA obligatoria** para: cambiar password/MFA, crear/borrar API keys, retiros, cambio de datos de destino, acciones admin de efecto.
6. **Tokens**: acceso JWT ≤ 15 min + refresh rotativo con detección de reuso (familia invalidada ante reuso); denylist en Redis para revocación inmediata (`< 5 s`).

### 1.8 Idempotencia (obligatoria en flujos financieros)

| Regla | Detalle |
|---|---|
| Rutas obligatorias | Todos los `POST` que crean/mueven dinero u órdenes: `orders`, `deposits`, `withdrawals`, `wallet/transfers`, `ledger/postings` (interno), webhooks entrantes, `reports` (jobs), y cualquier `POST` marcado **Sí** en las tablas §2 |
| Formato | `Idempotency-Key: <uuidv7>`; ausente en ruta obligatoria → `400 VALIDATION_ERROR` |
| Mecanismo | Persistir `(key, subject, ruta, hash_solicitud, respuesta, status, created_at)` con TTL **24 h** (configurable); misma clave + mismo hash → devuelve la respuesta almacenada con `Idempotent-Replay: true` y mismo status |
| Conflicto | Misma clave + hash distinto → `409 IDEMPOTENCY_KEY_REUSE`; ejecución concurrente en curso → `409 IDEMPOTENCY_IN_PROGRESS` con `Retry-After: 1` |
| Alcance | La clave es válida solo para (ruta, sujeto autenticado): evita colisiones entre actores |
| Estado interno | Máquina de estados del recurso sigue siendo idempotente (ej. `DELETE /orders/{id}` es repetible: cancelar dos veces = `200`/`409` documentado, nunca doble efecto) |
| Webhooks entrantes | Firma verificada (HMAC) + clave de entrega del proveedor; reintentos del proveedor deben reutilizar la misma clave → un solo asiento en ledger |
| Registro y auditoría | Cada replay se registra en `audit` con `request_id`, `correlation_id` y `idempotency_key` |

---

## 2. Mapa de Endpoints por Dominio

Convención de columna **Idem**: `Sí` = efecto único garantizado con `Idempotency-Key`; `N/A` = solo lectura; `No` = operación no repetible por diseño (documentado).

### 2.1 Health / Ready (Fase 1)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/health` | Liveness del gateway; sin detalle de dependencias | Pública (sin datos internos) | N/A | 1 |
| GET | `/api/v1/ready` | Readiness con estado de dependencias (Postgres/Redis/Redpanda) | Solo probes de red interna (IP allowlist); versión pública resume `ok/degraded` | N/A | 1 |
| GET | `/api/v1/version` | Versión de build, `mode`, `deprecations[]`, flags públicos | Pública | N/A | 1 |

### 2.2 Auth + Identity (Fase 1)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| POST | `/api/v1/auth/register` | Alta de usuario; crea cuenta DEMO por defecto (F2+) | Pública (rate limit duro, anti-bot) | No | 1 |
| POST | `/api/v1/auth/verify-email` | Verifica token de un solo uso enviado por email | Pública (token) | Sí | 1 |
| POST | `/api/v1/auth/resend-verification` | Reenvía verificación (respuesta siempre `202`, anti-enumeración) | Pública | Sí | 1 |
| POST | `/api/v1/auth/login` | Autenticación; devuelve `access_token` (≤15 min) + `refresh_token` rotativo + `session_id` | Pública (por IP y por cuenta) | No | 1 |
| POST | `/api/v1/auth/login/mfa` | Segundo factor (TOTP o código de respaldo) del flujo de login | Ticket de login de un solo uso | No | 1 |
| POST | `/api/v1/auth/refresh` | Rotación de refresh; reuso detectado invalida la familia completa | Refresh token | No | 1 |
| POST | `/api/v1/auth/logout` | Revoca la sesión actual (denylist Redis) | Sesión | Sí | 1 |
| POST | `/api/v1/auth/logout-all` | Revoca todas las sesiones del usuario | Sesión + step-up MFA | Sí | 1 |
| POST | `/api/v1/auth/password/change` | Cambio de password con password actual | Sesión + step-up MFA | Sí | 1 |
| POST | `/api/v1/auth/password-reset/request` | Solicita reset; respuesta genérica `202` (sin confirmar existencia) | Pública | Sí | 1 |
| POST | `/api/v1/auth/password-reset/confirm` | Confirma reset con token un solo uso; cierra sesiones previas | Token de un solo uso | Sí | 1 |
| GET | `/api/v1/auth/mfa/status` | Estado de MFA (totp activo, códigos de respaldo restantes) | Sesión | N/A | 1 |
| POST | `/api/v1/auth/mfa/activate` | Inicia enrolamiento TOTP; devuelve `otpauth://` + códigos de respaldo | Sesión + step-up MFA | No | 1 |
| POST | `/api/v1/auth/mfa/verify` | Confirma enrolamiento / verifica código | Sesión (o ticket de login en flujo 2FA) | No | 1 |
| POST | `/api/v1/auth/mfa/deactivate` | Desactiva MFA (auditable, notificación al usuario) | Sesión + step-up MFA | Sí | 1 |
| GET | `/api/v1/auth/sessions` | Lista sesiones activas (device, IP hasheada, última actividad) | Sesión | N/A | 1 |
| DELETE | `/api/v1/auth/sessions/{session_id}` | Revoca una sesión | Sesión (propia) o `admin` | Sí | 1 |
| GET | `/api/v1/auth/devices` | Dispositivos conocidos y huella asociada | Sesión | N/A | 1 |
| DELETE | `/api/v1/auth/devices/{device_id}` | Olvida dispositivo (fuerza re-login/re-MFA) | Sesión | Sí | 1 |
| GET | `/api/v1/auth/login-history` | Historial de logins y fallos (evento 3/4) | Sesión | N/A | 1 |
| GET | `/api/v1/me` | Perfil del sujeto (email, preferencias, jurisdiction ref) | Sesión o API key + `read` | N/A | 1 |
| PATCH | `/api/v1/me` | Actualiza preferencias/perfil no sensible | Sesión + `read` | Sí | 1 |

### 2.3 API Keys (Fase 1)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/api-keys` | Lista claves propias (nunca el secreto; solo prefijo/últimos 4) | Sesión | N/A | 1 |
| POST | `/api/v1/api-keys` | Crea clave con `scopes[]`, `expires_at`, `ip_whitelist`; secreto visible **una sola vez** | Sesión + step-up MFA | Sí | 1 |
| GET | `/api/v1/api-keys/{api_key_id}` | Detalle de clave | Sesión | N/A | 1 |
| PATCH | `/api/v1/api-keys/{api_key_id}` | Rota secreto / amplía o restringe scopes (peor caso: nunca amplía a `admin`) | Sesión + step-up MFA | Sí | 1 |
| DELETE | `/api/v1/api-keys/{api_key_id}` | Revoca clave (efecto inmediato en gateway) | Sesión | Sí | 1 |

### 2.4 Accounts (Fase 2)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/accounts` | Lista cuentas de trading propias (live/demo, moneda, jurisdicción, estado) | Sesión/API key + `read` | N/A | 2 |
| POST | `/api/v1/accounts` | Crea cuenta (DEMO siempre; LIVE requiere KYC + flag) | Sesión + step-up MFA | Sí | 2 |
| GET | `/api/v1/accounts/{account_id}` | Detalle de cuenta | `read` + pertenencia o `admin` | N/A | 2 |
| PATCH | `/api/v1/accounts/{account_id}` | Ajustes permitidos (alias, preferencias) | `read` + pertenencia | Sí | 2 |
| POST | `/api/v1/accounts/{account_id}/close` | Cierre de cuenta condicionado a saldo cero real en ledger (409 si no lo es; 403 `live-not-enabled` para LIVE) | Sesión | Opcional | 2 |
| POST | `/api/v1/accounts/{account_id}/reload-demo` | Recarga la demo a `demo_initial_balance`; emite `DemoBalanceReset` (#17) y responde `202` con `scheduled` | Sesión | **Sí (obligatoria)** | 2 |
| GET | `/api/v1/accounts/{account_id}/limits` | Límites de la cuenta (posición, pérdida diaria, apalancamiento) | `read` + pertenencia | N/A | 4 |
| GET | `/api/v1/accounts/{account_id}/status-history` | Historial de estados (activa, suspendida, cerrada) | `read` + pertenencia o `admin` | N/A | 7 |

> **Nota F2.3**: el cierre de cuentas exige hoy sólo sesión de usuario + saldo cero en ledger; la verificación de **KYC + step-up MFA** (columna "Auth" prevista) queda **diferida a F6**. El cierre emite `AccountClosed` (#39) y fija `closed_at`.

### 2.5 Wallet (Fase 2 — proyección; fuente de verdad = ledger)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/wallet/balances` | Balances multi-moneda (disponible/reservado) + `as_of` + indicador de reconciliación | `read` + pertenencia | N/A | 2 |
| GET | `/api/v1/wallet/balances/{currency}` | Balance por moneda | `read` + pertenencia | N/A | 2 |
| GET | `/api/v1/wallet/transactions` | Movimientos de saldo (cursor; `from`/`to` obligatorios, ventana ≤ 90 días) | `read` + pertenencia | N/A | 2 |
| POST | `/api/v1/wallet/transfers` | Transferencia interna entre cuentas propias (DEMO/LIVE sin cruce) | `payments` | **Sí** | 2 |
| GET | `/api/v1/wallet/conversion-rates` | Tasas de conversión vigentes (fuente y timestamp) | `read` | N/A | 2 |

> **Nota §2.5 (interpretación A→B)**: la transferencia debita el saldo real de la cuenta A en el ledger y acredita el mismo importe en B (`from_account_id` → `to_account_id`); wallet valida cuentas activas, mismo modo (demo/live) y misma moneda, y comprueba el saldo real vía `GET /internal/v1/balances` antes de escribir `POST /internal/v1/postings`. Sin saldo → `409` `urn:platform:error:insufficient-balance`; cuentas inactivas o cruce de modos → `409` `urn:platform:error:conflict`; cuentas inexistentes/ajenas → `404` idéntico (BOLA §1.7.3). La wallet sólo proyecta el resultado (evento `LedgerPosted` #38).
>
> **Nota FX (L §10, no determinado)**: hasta que se defina la fuente de tipo de cambio, `GET /api/v1/wallet/conversion-rates` responde `data: []`, `source: "none"` y `as_of: null`.

### 2.6 Ledger / Statements (Fase 2 — fuente de verdad)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/ledger/statements` | Extractos por periodo (cursor) | `read` + pertenencia | N/A | 2 |
| GET | `/api/v1/ledger/statements/{statement_id}` | Extracto con asientos y saldo inicial/final | `read` + pertenencia | N/A | 2 |
| GET | `/api/v1/ledger/entries` | Asientos propios (filtro `account_id`, `from/to` obligatorio) | `read` + pertenencia | N/A | 2 |
| POST | `/api/v1/ledger/statements/{statement_id}/export` | Export CSV/PDF cuadrado con `as_of` | `read` + pertenencia | **Sí** | 7 |
| GET | `/api/v1/admin/ledger/entries` | Asientos crudos (backoffice, cross-cuenta) | `admin` | N/A | 7 |
| POST | `/api/v1/admin/ledger/reconciliations` | Ejecuta reconciliación ledger↔wallet | `admin` + 4-ojos | **Sí** | 7 |

> Los asientos **nunca** se crean ni modifican por API pública: los postings ocurren solo en `/internal/v1/postings` desde servicios de negocio (§3).

### 2.7 Market Data (overview en Fase 1; ticks/velas en Fase 3)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/market-data/overview` | Snapshot público de Forex/Crypto de referencia (proveedores keyless; `source` + `ts` + `stale`, jamás precio inventado) | **Pública** | N/A | **1** (2026-09-28) |
| GET | `/api/v1/market-data/symbols` | Símbolos disponibles con sesión de mercado (`open`/`closed`/`halted` + `next_open`/`next_close`) y estado del feed | **Pública** (en `PUBLIC_PATHS` del gateway) | N/A | **3** (2026-10-01) |
| GET | `/api/v1/market-data/ticks/{symbol}` | Último tick (snapshot) | `read` | N/A | **3** (2026-10-01) |
| GET | `/api/v1/market-data/ticks` | Histórico de ticks (cursor, rango ≤ 24 h) | `read` | N/A | **3** (2026-10-01) |
| GET | `/api/v1/market-data/candles/{symbol}/{timeframe}` | Velas OHLC (cursor, `from/to`) | `read` | N/A | **3** (2026-10-01) |
| GET | `/api/v1/market-data/status` | Estado del feed: `simulated/real`, latencia, huecos detectados | `read` | N/A | **3** (2026-10-01) |
| GET | `/api/v1/admin/market-data/providers` | Estado de adapters de proveedores | `admin` | N/A | 7 |

> El `overview` (Fase 1) sirve datos **reales** de APIs públicas keyless con `simulated: false` (BCE/Frankfurter, Kraken; ver `docs/API_INTEGRATIONS.md`), solo para consulta informativa en la portada. Todo dato de mercado de Fases 3–5 (trading/mark-to-market) sigue siendo **simulado** y va etiquetado (`simulated: true`); ver 00-decisions §6 y X-07.

### 2.8 Instruments (Fase 3)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/instruments` | Catálogo de instrumentos (cursor, filtros por tipo/estado) | `read` o pública | N/A | **3** (2026-10-01) |
| GET | `/api/v1/instruments/{symbol}` | Instrumento (specs mínimos) | `read` o pública | N/A | **3** (2026-10-01) |
| GET | `/api/v1/instruments/{symbol}/specs` | Especificaciones completas: tick size, tamaño de lote, horarios, margen, costes | `read` | N/A | **3** (2026-10-01) |
| GET | `/api/v1/instruments/{symbol}/contract-details` | Detalle contractual y reglas de liquidación (derivados) | `read` | N/A | 5 |
| GET | `/api/v1/admin/instruments` | Catálogo administrable | `admin` | N/A | 3 |

> BUILD-028 (2026-10-01): `instruments`, `instruments/{symbol}` y `.../specs` implementados en `services/market-data` con scope `read`; los tres aceptan el símbolo canónico con `/` (tramo literal o percent-encoded) y sirven la spec vigente por tiempo (`instrument_specs`, REQ-025) más el estado de mercado con `next_open`/`next_close` (REQ-099). `/admin/instruments` queda pendiente de abrir el prefijo `/api/v1/admin/` hacia `market-data` en el gateway (hoy ese prefijo rutea a `identity`).

### 2.9 Orders (Fase 4)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| POST | `/api/v1/orders` | Crea orden (market/limit/stop; `client_order_id` + `Idempotency-Key`) | `trade` + cuenta con KYC + flag | **Sí** | 4 |
| GET | `/api/v1/orders` | Lista órdenes (filtros `account_id`, `status`, `symbol`, `from/to`) | `read` (+ `trade` para detalle de ejecución) | N/A | 4 |
| GET | `/api/v1/orders/{order_id}` | Detalle de orden | `read` + pertenencia o `admin` | N/A | 4 |
| PATCH | `/api/v1/orders/{order_id}` | Modifica precio/cantidad/SL-TP (revalida margen) | `trade` + pertenencia | **Sí** | 4 |
| DELETE | `/api/v1/orders/{order_id}` | Cancela orden (idempotente por naturaleza) | `trade` + pertenencia | Sí | 4 |
| POST | `/api/v1/orders/{order_id}/cancel-all` | Cancela todas las órdenes de la cuenta/filtro | `trade` | **Sí** | 4 |
| GET | `/api/v1/orders/{order_id}/fills` | Ejecuciones de la orden (cursor) | `read` + pertenencia | N/A | 4 |
| POST | `/api/v1/orders/batch` | Órdenes en lote (máx 50; resultado por elemento) | `trade` + scope bot (F5) | **Sí** | 5 |

### 2.10 Positions (Fase 4)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/positions` | Posiciones abiertas por cuenta (cursor) | `read` + pertenencia | N/A | 4 |
| GET | `/api/v1/positions/{position_id}` | Detalle (entrada, margen, PnL no realizado) | `read` + pertenencia | N/A | 4 |
| POST | `/api/v1/positions/{position_id}/close` | Cierre total/parcial (`size` en body) | `trade` + pertenencia | **Sí** | 4 |
| GET | `/api/v1/positions/{position_id}/history` | Historial de la posición (aperturas, cierres, swaps, fees) | `read` + pertenencia | N/A | 4 |
| GET | `/api/v1/positions/margin-summary` | Margen usado/libre/nivel por cuenta | `read` + pertenencia | N/A | 4 |

### 2.11 Trades (Fase 4)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/trades` | Historial de ejecuciones consolidadas (cursor, `from/to`) | `read` + pertenencia | N/A | 4 |
| GET | `/api/v1/trades/{trade_id}` | Detalle de ejecución (comisión, `ledger_tx_id`) | `read` + pertenencia | N/A | 4 |

### 2.12 Reports (Fase 7)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/reports` | Lista de jobs de reporte propios | `read` + pertenencia | N/A | 7 |
| POST | `/api/v1/reports` | Crea job (posición, PnL, fiscal, actividad) con filtros y formato | `read` + pertenencia | **Sí** | 7 |
| GET | `/api/v1/reports/{report_id}` | Estado del job + URL firmada de descarga temporal | `read` + pertenencia | N/A | 7 |
| GET | `/api/v1/reports/{report_id}/download` | Descarga (CSV/PDF) con expiración corta | `read` + pertenencia | N/A | 7 |
| POST | `/api/v1/admin/reports/regulatory` | Reportes regulatorios | `admin` + 4-ojos | **Sí** | 7 |
| GET | `/api/v1/admin/reports` | Todos los reportes | `admin` | N/A | 7 |

### 2.13 Payments — depósitos/retiros (Fase 6)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/payment-methods` | Métodos disponibles por jurisdicción/moneda (evaluado por flags/jurisdicción) | `read` | N/A | 6 |
| POST | `/api/v1/deposits` | Inicia depósito (adapter PSP) | `payments` + KYC vigente | **Sí** | 6 |
| GET | `/api/v1/deposits` | Historial de depósitos (cursor, `from/to`) | `read` + pertenencia | N/A | 6 |
| GET | `/api/v1/deposits/{deposit_id}` | Estado del depósito (evento 18–20) | `read` + pertenencia | N/A | 6 |
| POST | `/api/v1/withdrawals` | Solicita retiro (reserva de fondos + revisión) | `payments` + KYC + step-up MFA | **Sí** | 6 |
| GET | `/api/v1/withdrawals` | Historial de retiros | `read` + pertenencia | N/A | 6 |
| GET | `/api/v1/withdrawals/{withdrawal_id}` | Estado del retiro (eventos 21–24) | `read` + pertenencia | N/A | 6 |
| POST | `/api/v1/withdrawals/{withdrawal_id}/cancel` | Cancela retiro pendiente de revisión | `payments` + pertenencia | **Sí** | 6 |
| POST | `/api/v1/payments/webhooks/{provider}` | Webhook entrante del PSP: firma HMAC + clave de entrega; **sin** JWT | Firma verificada | **Sí** | 6 |

> Retiros reales y payouts = `REQUIERE PROVEEDOR` + `REQUIERE LICENCIA` (`X-blocked-to-live.md`); en Fase 6 con `live_trading=false` el flujo opera en modo DEMO/sandbox.

### 2.14 KYC (Fase 6)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/kyc/status` | Estado KYC propio (tier, requisitos faltantes) | `read` | N/A | 6 |
| POST | `/api/v1/kyc/cases` | Abre caso KYC | Sesión + step-up MFA | **Sí** | 6 |
| GET | `/api/v1/kyc/cases` | Casos propios | `read` + pertenencia | N/A | 6 |
| GET | `/api/v1/kyc/cases/{kyc_case_id}` | Detalle del caso (sin PII sensible en claro) | `read` + pertenencia | N/A | 6 |
| POST | `/api/v1/kyc/cases/{kyc_case_id}/documents` | Sube documento (máx 8 MiB, tipos permitidos, hash) | `read` + pertenencia | **Sí** | 6 |
| POST | `/api/v1/kyc/cases/{kyc_case_id}/submit` | Envía caso a revisión | `read` + pertenencia | **Sí** | 6 |
| GET | `/api/v1/admin/kyc/cases` | Cola de revisión (backoffice) | `admin` | N/A | 7 |
| POST | `/api/v1/admin/kyc/cases/{kyc_case_id}/approve` | Aprueba caso (4-ojos, motivo obligatorio) | `admin` + 4-ojos | **Sí** | 7 |
| POST | `/api/v1/admin/kyc/cases/{kyc_case_id}/reject` | Rechaza caso (motivo, `retry_allowed`) | `admin` + 4-ojos | **Sí** | 7 |

### 2.15 Admin / Backoffice (Fase 7)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/admin/users` | Búsqueda de usuarios (PII enmascarada por defecto) | `admin` | N/A | 7 |
| GET | `/api/v1/admin/users/{user_id}` | Vista 360 (ensamblada vía APIs internas, sin joins cross-servicio) | `admin` | N/A | 7 |
| POST | `/api/v1/admin/users/{user_id}/suspend` | Suspende usuario y revoca sesiones | `admin` + 4-ojos | **Sí** | 7 |
| DELETE | `/api/v1/admin/users/{user_id}/sessions` | Revoca todas las sesiones de un usuario | `admin` | Sí | 7 |
| POST | `/api/v1/admin/withdrawals/{withdrawal_id}/approve` | Aprueba retiro (colas manuales, 4-ojos) | `admin` + 4-ojos | **Sí** | 7 |
| POST | `/api/v1/admin/withdrawals/{withdrawal_id}/reject` | Rechaza retiro con motivo | `admin` + 4-ojos | **Sí** | 7 |
| GET | `/api/v1/admin/audit-exports` | Exportaciones de auditoría (job) | `admin` | N/A | 7 |
| POST | `/api/v1/admin/audit-exports` | Crea export (rango + formato, torrente firmado) | `admin` + 4-ojos | **Sí** | 7 |
| GET | `/api/v1/admin/system/status` | Estado de servicios, flags y modo | `admin` | N/A | 7 |

### 2.16 Feature Flags (Fase 1 evaluación / Fase 7 administración)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/feature-flags` | Evaluación de flags para el sujeto (incluye `live_trading=false`) | Sesión/API key | N/A | 1 |
| GET | `/api/v1/admin/feature-flags` | Flags con targeting y rollout | `admin` | N/A | 7 |
| PUT | `/api/v1/admin/feature-flags/{flag_key}` | Cambia valor/targeting (auditable; `live_trading` es **inmutable**) | `admin` + 4-ojos | **Sí** | 7 |

### 2.17 Audit (servicio Fase 1; API pública Fase 7)

| Método | Ruta | Descripción | Auth / Scope | Idem | Fase |
|---|---|---|---|---|---|
| GET | `/api/v1/audit/entries` | Consulta del log inmutable (filtros `actor`, `action`, `correlation_id`, `from/to`) | `admin` (o rol `auditor`, solo lectura) | N/A | 7 |
| GET | `/api/v1/audit/entries/{entry_id}` | Entrada conchain de integridad | `admin`/`auditor` | N/A | 7 |
| GET | `/api/v1/audit/correlation/{correlation_id}` | Trazas de una request end-to-end | `admin`/`auditor` | N/A | 7 |

> En Fase 1 el servicio `audit` existe y consume eventos, pero **no** publica API externa: su consulta es por red interna (§3) hasta la llegada del backoffice en Fase 7.

### 2.18 Fases 8–9 (fuera de este mapa)

| Fase | Contenido | Nota |
|---|---|---|
| 8 | APIs de `crm-support`, `affiliate-ib`, `p2p` (tickets, referidos, transferencias P2P) | Dominios no incluidos en este mapa; se mapean en documento propio antes de construir |
| 9 | Activación LIVE: sin rutas nuevas; solo gating de flags, licencias y proveedores | Todo endpoint marcado LIVE pasa de `MOCK/DEMO` a real solo con evidencia en `X-blocked-to-live.md` |

---

## 3. Endpoints Internos Servicio-a-Servicio (no expuestos en el gateway)

Superficie `/internal/v1/`: bloqueada en el edge, solo red de servicio, nunca con datos de refresh tokens.

| Servicio | Método + Ruta (interna) | Consumidor | Propósito | Auth interna | Fase |
|---|---|---|---|---|---|
| identity | `GET /internal/v1/users/{user_id}` | accounts, kyc, admin | Perfil mínimo para vistas 360 | mTLS + JWT de servicio | 1 |
| identity | `GET /internal/v1/users/{user_id}/authorizations` | gateway (opcional), admin | Roles/scope efectivos (complementa JWT) | mTLS + JWT de servicio | 1 |
| identity | `POST /internal/v1/sessions/revoke` | admin, risk | Revocación programática (denylist) | mTLS + JWT de servicio | 1 |
| identity | `POST /internal/v1/api-keys/introspect` | gateway | Validación de API key + scope + IP whitelist | mTLS + JWT de servicio | 1 |
| identity | `GET /internal/v1/jwks.json` | gateway | Claves públicas JWT (rotación de claves) | Red interna (GET público de clave) | 1 |
| accounts | `GET /internal/v1/accounts/{account_id}` | wallet, ledger, trading, payments, kyc, admin | Validación de cuenta, estado, jurisdicción | mTLS + JWT de servicio | 2 |
| wallet | `GET /internal/v1/accounts/{account_id}/balances` | trading, payments | Disponible/reservado para pre-trade y retiros | mTLS + JWT de servicio | 2 |
| wallet | `POST /internal/v1/reservations` | trading, payments | Reserva/liberación de fondos (hold) | mTLS + JWT de servicio + `Idempotency-Key` | 2 |
| ledger | `POST /internal/v1/postings` | wallet, trading, payments | Asiento double-entry (única vía de escritura) | mTLS + JWT de servicio + `Idempotency-Key` | 2 |
| ledger | `GET /internal/v1/postings/{posting_id}` | wallet, admin | Verificación de asiento | mTLS + JWT de servicio | 2 |
| ledger | `GET /internal/v1/balances` (`?owner_id=` opcional) | accounts (cierre/recarga), wallet (reconciliador) | Saldo por propietario y moneda: Σcréditos − Σdébitos en cuentas no control (L §4.1) | mTLS + JWT de servicio | 2 |
| risk | `POST /internal/v1/risk/pre-trade-check` | trading | Validación de límites/margen previa a la orden | mTLS + JWT de servicio | 4 |
| market-data | `GET /internal/v1/market-data/quote/{symbol}` | trading, risk | Snapshot de precio para margen/orden | mTLS + JWT de servicio | 3 |
| trading | `POST /internal/v1/orders` | bots, copy-trading | Órdenes programáticas con scope acotado | mTLS + JWT de servicio + `Idempotency-Key` | 5 |
| payments | `POST /internal/v1/payments/holds` / `release` | ledger, wallet | Reserva de fondos para retiro en revisión | mTLS + JWT de servicio + `Idempotency-Key` | 6 |
| kyc | `GET /internal/v1/kyc/status/{user_id}` | accounts, payments, admin | Tier/vigencia KYC | mTLS + JWT de servicio | 6 |
| feature-flags | `GET /internal/v1/flags/evaluate` | todos | Evaluación server-side de flags | mTLS + JWT de servicio | 1 |
| audit | `GET /internal/v1/audit/entries` | admin, soporte (F8) | Lectura del log inmutable | mTLS + JWT de servicio | 1 |
| — | *cualquier `/internal/*` vía gateway* | — | **Prohibido**: edge responde `404` | — | — |

### 3.1 Autenticación entre servicios

| Capa | Regla |
|---|---|
| Transporte | mTLS en la red de servicio (certificados por servicio, rotación automatizada); sin tráfico interno en claro |
| Token de servicio | JWT de servicio con TTL **≤ 5 min**, `iss=platform-internal`, `sub=svc:<nombre>`, `scope=svc:<nombre>` (no hereda scopes de usuario) |
| Propagación de usuario | Solo `x-user-id`/`x-on-behalf-of` firmado (JWT corto con `act` claim) para auditoría; **prohibido** propagar refresh tokens o cookies entre servicios |
| Trazabilidad | `x-request-id` y `x-correlation-id` obligatorios en todo hop; se heredan a eventos y audit |
| Idempotencia | Toda mutación financiera interna lleva `Idempotency-Key` (misma clave del request externo cuando aplica) |
| Rate limit | Cuota por par (origen, destino) + circuit breaker ante fallos; sin malla de servicios en Fase 1 (00-decisions §4): reglas estáticas en cada cliente HTTP |
| Autorización | El servicio destino revalida pertenencia de recursos (no confía ciegamente en el gateway) |
| Eventos | La comunicación preferente es asíncrona vía Redpanda (outbox); el síncrono se usa solo cuando se necesita respuesta inmediata |

---

## 4. Contratos: OpenAPI, Cliente TypeScript y Contract Tests

| Elemento | Regla |
|---|---|
| Fuente única | `services/<svc>/openapi.yaml` (OpenAPI 3.1) por servicio: **es** el contrato. No hay especificación paralela en código ni en wiki |
| Cobertura | Cada ruta pública e interna vive en el `openapi.yaml` del servicio propietario; el gateway compone sus rutas a partir de ellos (incluye `servers` `/api/v1`) |
| Validación en CI | Lint de spec (estilo + referencias íntegras), ejemplificación de ejemplos, y que toda ruta del código FastAPI aparezca en la spec (o el build falla) |
| Cliente generado | `packages/api-client` se **genera** desde las specs (`// @generated`); prohibido editar a mano. Expone tipos TS, runtime de errores problem+json, manejo de `Idempotency-Key` y reintentos |
| Generadores | Cliente TS público (`/api/v1`) y cliente TS/Python interno (`/internal/v1`); regeneración en CI si las specs cambiaron |
| Versionado de contrato | Major = número en path; minor = aditivo. Changelog por servicio (`services/<svc>/CHANGELOG.md`) con secciones `Added/Changed/Deprecated/Removed/Breaking` |
| Compatibilidad | Reglas §1.2 aplicadas por diff de spec contra la rama base; breaking ⇒ falla CI salvo bump de major |
| Contract tests | (1) *spec diff gate*; (2) tests request/response contra la spec (payload real ∈ esquema); (3) tests de integración consumidor↔productor en compose; (4) **consumer-driven** obligatorio para rutas financieras (`orders`, `payments`, `ledger`) antes de merge |
| Publicación | Specs versionadas en el repo y servidas en `GET /api/v1/openapi.json` (solo pública) / artefacto interno por servicio |
| WS | El protocolo `/ws/v1` se especifica como AsyncAPI en `services/market-data/asyncapi.yaml` cuando arranque Fase 3 (mismo principio de contrato único; aún `PENDIENTE`) |

---

## 5. Límites y Quotas por Ruta

Aplicados en `gateway` (Redis, sliding window) + refuerzo en el servicio para rutas financieras. Todo exceso → `429` + `Retry-After` + problem+json `RATE_LIMITED`.

| Clase | Rutas típicas | Límite default | Pico (burst) | Ventana | Quota de negocio |
|---|---|---|---|---|---|
| Pública estricta (auth) | `POST /auth/login`, `/auth/register`, `/auth/password-reset/request` | 10 req/min por IP **y** 5/min por cuenta/email | 5 | 1 min | Backoff exponencial tras 5 fallos; bloqueo temporal de cuenta a 20 fallos/15 min |
| Refresh | `POST /auth/refresh` | 30/min por sujeto | 5 | 1 min | Reuso de refresh → invalidación de familia (no aplica cuota) |
| Escritura identidad | `POST /auth/mfa/*`, `api-keys`, `password/change` | 30/min por sujeto | 5 | 1 min | Step-up MFA independiente de la cuota |
| Lectura estándar | `GET` de colecciones propias | 600/min por token | 50/s | 1 min | Rango de consulta ≤ 90 días |
| Lectura pesada | `ledger/*`, `trades`, `audit/entries`, exports | 60/min por sujeto | 10/s | 1 min | 10 jobs de export/hora, 24/día por sujeto |
| Market data REST | `market-data/*`, `instruments/*` | 300/min por token | 20/s | 1 min | Histórico ≤ 24 h por request (ticks) |
| Trading | `POST /orders`, `PATCH /orders/*`, `DELETE /orders/*` | 120/min por cuenta | 10/s | 1 min | Máx 100 órdenes abiertas por cuenta (regla de negocio) |
| Payments | `POST /deposits`, `POST /withdrawals`, `wallet/transfers` | 20/min por cuenta | 2/s | 1 min | Retiros: máx 10/día por cuenta y monto diario por jurisdicción |
| KYC | `POST /kyc/*` | 10/min por sujeto | 2/s | 1 min | Reintentos de caso: 5/día |
| Admin/backoffice | `/admin/*` | 300/min por operador | 10/s | 1 min | Acciones 4-ojos: 60/hora por operador |
| Webhooks entrantes | `POST /payments/webhooks/*` | 100/min por IP del proveedor | 20/s | 1 min | Reintentos del proveedor reutilizan `Idempotency-Key` |
| Global por IP | Todas | 1000/min por IP | — | 1 min | Protección anti-DDoS de aplicación |
| Conexiones | Handshake WS y login | 5 conexiones WS/usuario; 10 logins/min/IP | — | 1 min | Detalle en `R-websocket-map.md` §6 |

**Comportamiento ante límite**: headers `RateLimit-*` siempre presentes en rutas limitadas; al agotarse, `429` con `Retry-After` y cuerpo problem+json `QUOTA_EXCEEDED` cuando corresponda a cuota de negocio (no a tasa). Las cuotas por ruta se declaran también en cada operación del `openapi.yaml` (`x-rate-limit`) para que el cliente las conozca sin leer este documento.

---

## 6. Pendientes / No Determinado

| Tema | Estado |
|---|---|
| Gateway de API management/comercial, portal de desarrolladores | `DECIDIR` (no se selecciona proveedor en Fase 0) |
| Firma de URLs de descarga de reportes (torrente) | `DECIDIR` Fase 7 (duración, alcance) |
| Versionado de webhooks salientes (payload al proveedor PSP) | `DECIDIR` Fase 6 (`{ "event_type", "schema_version" }` siguiendo `P`) |
| GraphQL / BFF móvil propio | `NO ADOPTADO` (REST + WS; reevaluar con evidencia) |
| Scope `admin` granular por recurso (RBAC fino) | `PENDIENTE` Fase 7 (`D-domain-map` §5) |

---

*Fin del documento Q-api-map.md*
