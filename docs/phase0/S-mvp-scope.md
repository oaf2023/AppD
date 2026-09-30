# S — MVP Scope (Alcance del MVP)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)

## 1. Resumen Ejecutivo

Este documento define el **alcance mínimo verificable** del MVP (Minimum Viable Product) para MonedasAR. El MVP se entrega en **dos fases secuenciales autorizadas**:

- **Fase 1 — Foundation** (autorizada): Identidad, Auditoría, Gateway, Shell Web, Infraestructura, Observabilidad.
- **Fase 2 — Account & Demo** (autorizada; en ejecución — F2.1 `ledger` y F2.2 `accounts` IMPLEMENTADOS 2026-09-30, ver `docs/component-status.md`): Cuenta demo, Wallet demo, Ledger, Market Data básico, Trading demo (órdenes, posiciones, PnL, SL/TP, cierre, historial).

**Regla de oro**: En el inicio de la Fase 1, **todo es `PENDIENTE` salvo los documentos de diseño**. No se declara `IMPLEMENTADO` sin código, tests y evidencia de ejecución.

---

## 2. Alcance por Fase

### 2.1 Fase 1 — Foundation (AUTORIZADA)

| Área | Componentes | Estado Inicial |
|------|-------------|----------------|
| **Identidad** | Registro email/password, verificación email, login, logout, sesión JWT (≤15 min), refresh token rotativo con detección de reuso, MFA TOTP (flag), recovery, devices, login history, RBAC básico (user/admin) | `PENDIENTE` |
| **Auditoría** | Consumer de eventos → log append-only inmutable (PostgreSQL), índices por correlation_id/aggregate_id/timestamp, API de consulta (admin), retención configurable | `PENDIENTE` |
| **Gateway** | TLS termination, routing, JWT validation, rate limit (global/por cliente), security headers, request-id, correlation OTel, circuit breaker básico, health/readiness | `PENDIENTE` |
| **Shell Web (apps/web)** | Next.js 15 PWA: landing, registro, login, dashboard vacío (placeholder), settings, i18n/RTL, Service Worker, offline-first básico | `PENDIENTE` |
| **Admin Shell (apps/admin-shell)** | Host MFE, login admin, navegación vacía, RBAC UI placeholder | `PENDIENTE` |
| **Infraestructura** | Monorepo (apps/services/packages/infrastructure), docker-compose local, PostgreSQL 17 (schemas aislados), Redis 7, Redpanda, CI/CD GitHub Actions, migraciones versionadas | `PENDIENTE` |
| **Observabilidad** | OTel Collector, Prometheus, Grafana, Loki, Tempo; dashboards básicos (RED metrics por servicio), alertas SLO placeholder, trazas W3C | `PENDIENTE` |
| **Documentación de diseño** | Docs phase0 (A–Z), ADRs base | `IMPLEMENTADO` (este documento) |

### 2.2 Fase 2 — Account & Demo (AUTORIZADA; en ejecución)

| Área | Componentes | Estado Inicial |
|------|-------------|----------------|
| **Accounts** | Crear cuenta demo, perfil, jurisdicción, estado, límites demo | `PENDIENTE` |
| **Wallet (demo)** | Balances multi-moneda virtual (proyección verificada vs ledger), consulta saldo, movimientos | `PENDIENTE` |
| **Ledger (demo)** | Double-entry append-only, asientos demo (deposit/withdraw/trade/fee/PnL), conciliación, inmutabilidad | `PENDIENTE` |
| **Market Data (demo)** | Adapter simulado (mock), normalización, cache Redis, streaming WS (ticks, candles 1m/5m/1h), símbolos demo | `PENDIENTE` |
| **Trading (demo)** | OMS/EMS: órdenes market/limit/stop, ejecución simulada (matching interno), posiciones, margen, PnL tiempo real, SL/TP, cierre, historial órdenes/positions | `PENDIENTE` |
| **Risk (demo)** | Límites notionales, max posición, max órdenes/día, kill switch cuenta, margin call simulado | `PENDIENTE` |
| **Notification (demo)** | Email (adapter mock), in-app, preferencias básicas | `PENDIENTE` |

> `Estado Inicial` = snapshot al inicio de la Fase 1 (Regla de oro §1). Progreso real
> al 2026-09-30: **Ledger** F2.1 `IMPLEMENTADO`, **Accounts** F2.2 `IMPLEMENTADO` y
> **Wallet** F2.3 `IMPLEMENTADO` (balances proyectados desde el ledger con reconciliador,
> movimientos con referencia al asiento, transferencias internas idempotentes,
> extractos JSON §2.6, cierre de cuenta con saldo cero y recarga de demo vía
> evento #17; Market Data avanzado, Trading/Risk/Notification siguen `PENDIENTE` );
> fuente: `docs/component-status.md`.

---

## 3. Fuera de Alcance Explícito (Out of Scope)

| Ítem | Justificación |
|------|---------------|
| **LIVE trading (dinero real)** | Requiere licencia, proveedor ejecución, contratos legales, compliance, auditoría externa. Bloqueado por `feature_flag live_trading = false`. |
| **KYC/AML real** | Requiere proveedor KYC (`REQUIERE PROVEEDOR`), integración legal, decision engine. Fase 6. |
| **Pagos/Retiros reales (PSP, banco, crypto)** | Requiere proveedores (`REQUIERE PROVEEDOR`), compliance, reconciliación. Fase 6. |
| **Market data real (feeds profesionales)** | Requiere licencias de datos (`REQUIERE LICENCIA`), contratos, SLA. Fase 3+ con proveedor. |
| **Ejecución externa (brokers, venues)** | Requiere conectividad FIX/REST, contratos, clearing. Fase 9 (LIVE integration). |
| **Backoffice completo (admin MFEs funcionales)** | Fase 7. Fase 1 solo shell vacío. |
| **Passkeys/WebAuthn** | `PENDIENTE` evaluación; no en MVP. |
| **Multi-región / DR / HA producción** | Fase 8 (Production Hardening). |
| **GraphQL / gRPC público** | Solo REST/JSON + WS en MVP. |
| **App nativa iOS/Android** | PWA only en MVP. |
| **White-label / multi-tenant** | No en roadmap actual. |

---

## 4. Criterios de Aceptación del MVP (Checklist Verificable)

> **Instrucción**: Cada ítem debe ser **demostrable** (curl, UI, test automatizado, log). Marcar `✅` solo con evidencia.

### 4.1 Fase 1 — Identity & Access

| # | Criterio | Verificación | Estado |
|---|----------|--------------|--------|
| 1.1 | Registro usuario con email + password (Argon2id) | `POST /auth/register` → 201, hash Argon2id en BD, evento `UserRegistered` en Redpanda | `PENDIENTE` |
| 1.2 | Verificación email (token expirable, single-use) | Click link → `GET /auth/verify-email?token=` → 200, `email_verified=true`, evento `EmailVerified` | `PENDIENTE` |
| 1.3 | Login → Access JWT (≤15 min) + Refresh token (rotativo, HttpOnly cookie) | `POST /auth/login` → 200, `access_token` JWT RS256, `refresh_token` cookie secure, evento `UserLoggedIn` | `PENDIENTE` |
| 1.4 | Refresh token rotation + detección reuso | Usar refresh → nuevo access + nuevo refresh; reusar refresh anterior → revocar familia, 401, evento `TokenReuseDetected` | `PENDIENTE` |
| 1.5 | Logout → revoca refresh token, invalida access (blocklist Redis) | `POST /auth/logout` → 200, refresh revocado, access en blocklist hasta expiración | `PENDIENTE` |
| 1.6 | MFA TOTP (opcional por flag) | `POST /auth/mfa/enable` → QR/secret; `POST /auth/mfa/verify` → 200, evento `MFAEnabled` | `PENDIENTE` |
| 1.7 | Recuperación cuenta (reset password token) | `POST /auth/password/reset-request` → email mock; `POST /auth/password/reset` → hash nuevo, evento `PasswordChanged` | `PENDIENTE` |
| 1.8 | Devices / Login History | `GET /auth/devices` → lista; `GET /auth/login-history` → paginado; evento `DeviceAdded` | `PENDIENTE` |
| 1.9 | RBAC básico: scope `user` vs `admin` en JWT | Login admin → JWT `scope=admin`; acceso `apps/admin-shell` permitido; user → 403 | `PENDIENTE` |
| 1.10 | Gateway valida JWT en todas las rutas protegidas | Request sin token → 401; token expirado → 401; token firmado incorrecto → 403 | `PENDIENTE` |
| 1.11 | Rate limit: login (5/min/IP), register (3/min/IP), API (100/s/cliente) | Exceder límite → 429 `Retry-After`, headers `X-RateLimit-*` | `PENDIENTE` |
| 1.12 | Security headers en todas las respuestas | `Strict-Transport-Security`, `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` | `PENDIENTE` |
| 1.13 | Request-id + correlation-id propagados (W3C traceparent) | Header `X-Request-ID` en respuesta; `traceparent` en logs OTel de todos los servicios | `PENDIENTE` |
| 1.14 | Circuit breaker básico en gateway (identity down → 503 rápido) | Apagar identity → gateway devuelve 503 en <100ms sin timeout | `PENDIENTE` |
| 1.15 | Health/Readiness endpoints en todos los servicios | `GET /healthz` (liveness), `GET /readyz` (readiness con deps) | `PENDIENTE` |

### 4.2 Fase 1 — Infra & Observabilidad

| # | Criterio | Verificación | Estado |
|---|----------|--------------|--------|
| 2.1 | docker-compose up → todos los contenedores healthy | `docker compose ps` → all `healthy`/`running` | `PENDIENTE` |
| 2.2 | Migraciones PostgreSQL versionadas (Alembic) aplicables/idempotentes | `alembic upgrade head` → 0 errores; `alembic downgrade -1` → rollback limpio | `PENDIENTE` |
| 2.3 | CI/CD: PR → lint, type-check, unit tests, build images, push registry | GitHub Actions verde en PR; imágenes en GHCR | `PENDIENTE` |
| 2.4 | OTel Collector recibe traces/metrics/logs de gateway, identity, audit | Grafana: dashboards RED (rate, error, duration) por servicio con datos reales | `PENDIENTE` |
| 2.5 | Loki: logs estructurados JSON con `service`, `level`, `trace_id` | Query Loki `{service="identity"} |= "UserLoggedIn"` → resultados | `PENDIENTE` |
| 2.6 | Tempo: trazas end-to-end (web → gateway → identity → postgres) | Trace ID desde browser → spans en Tempo con latencia por hop | `PENDIENTE` |
| 2.7 | Prometheus: alertas placeholder (up, latency p99 > 1s, error rate > 1%) | Alertmanager disparando en condiciones de test | `PENDIENTE` |
| 2.8 | Redpanda: topics creados, retention 7d, producer/consumer funcionando | `rpk topic list`; produce/consume manual → mensajes visibles | `PENDIENTE` |
| 2.9 | Transactional outbox en identity → eventos en Redpanda sin pérdida | Apagar Redpanda → identity sigue aceptando writes; al recuperar → eventos publicados | `PENDIENTE` |

### 4.3 Fase 1 — Frontend (apps/web + admin-shell)

| # | Criterio | Verificación | Estado |
|---|----------|--------------|--------|
| 3.1 | Landing page SSR con SEO meta tags | `curl -I /` → 200, `<title>`, `<meta description>`, `og:*` tags | `PENDIENTE` |
| 3.2 | Registro → verificación email → login → dashboard (vacío) flow E2E | Playwright/Cypress test passing | `PENDIENTE` |
| 3.3 | PWA: Service Worker registrado, offline fallback, manifest | Lighthouse PWA score ≥ 90; `navigator.serviceWorker.controller` existe | `PENDIENTE` |
| 3.4 | i18n/RTL: cambio idioma (es/en/ar), RTL layout correcto | Cambiar a árabe → layout mirror, fuentes correctas | `PENDIENTE` |
| 3.5 | Admin shell: login admin → shell carga → navegación placeholder | E2E test admin login → shell render | `PENDIENTE` |
| 3.6 | Tailwind + design tokens consistentes (colors, spacing, radius) | Storybook/Chromatic visual regression baseline | `PENDIENTE` |

### 4.4 Fase 2 — Account & Demo Trading (Solo si Fase 2 autorizada)

| # | Criterio | Verificación | Estado |
|---|----------|--------------|--------|
| 4.1 | Crear cuenta demo desde dashboard | `POST /accounts/demo` → 201, cuenta en BD `accounts`, evento `DemoAccountCreated` | `PENDIENTE` |
| 4.2 | Saldo virtual inicial (ej. USD 10,000) visible en wallet | `GET /api/v1/wallet/balances` → `{"USD": "10000"}` (canónico ADR-0006) tras el fondeo #16; conciliación automática ledger↔wallet (reconciliador) | `IMPLEMENTADO` (F2.3, integration `test_wallet`) |
| 4.3 | Consulta mercados (símbolos demo) + gráfico candles 1m/5m/1h | `GET /market-data/symbols` → lista; `WS /market-data/stream` → ticks/candles en tiempo real | `PENDIENTE` |
| 4.4 | Orden demo: market buy EUR/USD 1.0 lot → ejecución simulada | `POST /trading/orders` → 201, `status=filled`, posición abierta, evento `OrderFilled` | `PENDIENTE` |
| 4.5 | Posición abierta → PnL tiempo real actualizado cada tick | `GET /trading/positions` → `unrealized_pnl` cambia con ticks | `PENDIENTE` |
| 4.6 | SL/TP configurables al crear orden o editar posición | `POST /trading/orders?sl=1.0850&tp=1.0950` → SL/TP activos; trigger → cierre automático | `PENDIENTE` |
| 4.7 | Cierre manual posición → realized PnL en wallet/ledger | `POST /trading/positions/{id}/close` → 200, asiento ledger `realized_pnl`, balance actualizado | `PENDIENTE` |
| 4.8 | Historial: órdenes, posiciones cerradas, PnL realizado | `GET /trading/history` → paginado, filtros, export CSV | `PENDIENTE` |
| 4.9 | Wallet → movimientos (depósito virtual, trade, fee, PnL, retiro virtual) | `GET /api/v1/wallet/transactions` → lista con `tx_type` y `ledger_transaction_id` (cursor, `from`/`to` ≤90 d) | `IMPLEMENTADO` (F2.3; tipos según eventos de la Fase 4+) |
| 4.10 | Ledger: asientos inmutables, double-entry, conciliación balance = suma asientos | Query SQL: `SELECT SUM(credit-debit) FROM ledger.entries WHERE account_id=X` = wallet balance (reconciliador `wallet` + `GET /internal/v1/balances`) | `IMPLEMENTADO` (F2.1+F2.3) |
| 4.11 | API Key (read-only demo) + WebSocket streaming | `POST /api-keys` → key + secret; `WS /v1/stream?api_key=` → market data + account updates | `PENDIENTE` |
| 4.12 | Statement PDF/CSV mensual (demo) | `GET /statements/monthly?month=2026-09` → 200, archivo generado en S3 (mock), link firmado | `PENDIENTE` |
| 4.13 | Backoffice admin: ver usuarios, cuentas, balances, órdenes, ledger entries | Admin shell → MFE `admin-users`, `admin-accounts`, `admin-ledger` con datos reales | `PENDIENTE` |

---

## 5. Tabla de Funcionalidades — Estado Exacto (Inicio Fase 1)

> **Convención**: Al inicio de Fase 1, **TODO es `PENDIENTE`** salvo la fila "Documentos de diseño (Phase 0 + ADRs base)". Esta tabla se actualiza **solo** al cerrar cada fase con evidencia.

| Funcionalidad | Fase | Estado | Evidencia Requerida para Cambiar Estado |
|---------------|------|--------|------------------------------------------|
| Documentos de diseño (Phase 0 A–Z + ADRs base) | 0 | **IMPLEMENTADO** | Archivos en `docs/phase0/`, `docs/adr/` |
| Monorepo structure + tooling (Turbo/Nx, lint, type-check) | 1 | `PENDIENTE` | `pnpm turbo run lint typecheck` verde |
| Docker Compose local (todos los servicios Fase 1) | 1 | `PENDIENTE` | `docker compose up -d` → all healthy |
| CI/CD GitHub Actions (lint, test, build, push) | 1 | `PENDIENTE` | Workflow verde en PR |
| PostgreSQL 17 + schemas aislados + migraciones Alembic | 1 | `PENDIENTE` | `alembic upgrade head` OK |
| Redis 7 (sesiones, rate-limit, cache) | 1 | `PENDIENTE` | `redis-cli ping` + keys visibles |
| Redpanda (topics, retention, outbox) | 1 | `PENDIENTE` | `rpk topic list` + produce/consume test |
| OTel Collector + Prometheus + Grafana + Loki + Tempo | 1 | `PENDIENTE` | Dashboards RED con datos reales |
| Gateway: TLS, routing, JWT validation, rate limit, headers, request-id, CB | 1 | `PENDIENTE` | Tests de contrato + load test básico |
| Identity: Register, Email Verify, Login, Refresh Rotation, Logout | 1 | `PENDIENTE` | E2E tests + eventos en Redpanda |
| Identity: MFA TOTP (flag), Recovery, Devices, Login History | 1 | `PENDIENTE` | Tests unitarios + E2E |
| Identity: RBAC (user/admin scopes) | 1 | `PENDIENTE` | Test JWT scopes |
| Audit: Consumer eventos → log inmutable + API consulta | 1 | `PENDIENTE` | Query audit log por correlation_id |
| apps/web: Landing, Auth Flow, Dashboard vacío, Settings, PWA, i18n/RTL | 1 | `PENDIENTE` | Lighthouse + Playwright E2E |
| apps/admin-shell: Host MFE, Admin Login, Nav placeholder | 1 | `PENDIENTE` | E2E admin login |
| Accounts: Cuenta demo, perfil, jurisdicción, límites | 2 | `PENDIENTE` | — |
| Wallet (demo): Balances multi-moneda, proyección verificada | 2 | `PENDIENTE` | — |
| Ledger (demo): Double-entry, append-only, conciliación | 2 | `PENDIENTE` | — |
| Market Data (demo): Adapter mock, normalización, WS streaming | 2 | `PENDIENTE` | — |
| Trading (demo): OMS/EMS, ejecución simulada, posiciones, PnL, SL/TP | 2 | `PENDIENTE` | — |
| Risk (demo): Límites, kill switch, margin call simulado | 2 | `PENDIENTE` | — |
| Notification (demo): Email mock, in-app, preferencias | 2 | `PENDIENTE` | — |
| KYC/AML (real) | 6 | `REQUIERE PROVEEDOR` | — |
| Payments/Withdrawals (real) | 6 | `REQUIERE PROVEEDOR` | — |
| Market Data (real feeds) | 3 | `REQUIERE LICENCIA/REGULACIÓN` | — |
| Live Execution (brokers/venues) | 9 | `REQUIERE LICENCIA/REGULACIÓN` | — |
| Backoffice Admin MFEs funcionales | 7 | `PENDIENTE` | — |
| Passkeys/WebAuthn | — | `PENDIENTE` | — |
| Multi-región / HA / DR Producción | 8 | `PENDIENTE` | — |
| Object Storage (S3-compatible) | 1 | `REQUIERE PROVEEDOR` | Config placeholder + adapter mock |
| Secrets Management (Vault/KMS) | 1 | `REQUIERE PROVEEDOR` | Config placeholder + env local |
| Feature Flag `live_trading` (siempre false en MVP) | 1 | `IMPLEMENTADO` (flag existe, false) | Código + test que valida flag=false |

---

## 6. Clasificación de Componentes (Glosario de Etiquetas)

| Etiqueta | Definición | Cuándo Usar |
|----------|------------|-------------|
| **IMPLEMENTADO** | Código escrito, tests pasando, desplegado en entorno de referencia (compose/CI), evidencia documentada | Solo al cerrar tarea con PR merged y CI verde |
| **PARCIAL** | Parte del flujo implementada (ej. register sí, email verify no); documentado qué falta | Cuando un epic se entrega en múltiples PRs |
| **MOCK** | Implementación funcional que simula dependencia externa (adapter con datos fijos/aleatorios); no usa proveedor real | Para desarrollo local y CI; nunca en producción |
| **PENDIENTE** | Diseñado (existe en docs/ADR), no implementado; autorizado para fase futura | Estado por defecto al inicio de fase |
| **REQUIERE PROVEEDOR** | Bloqueado por dependencia externa no resuelta (S3, Vault, KYC provider, PSP, Market Data Feed) | Identificado en Fase 0; requiere decisión de negocio |
| **REQUIERE LICENCIA/REGULACIÓN** | Bloqueado legalmente (LIVE trading, ejecución real, feeds profesionales, custodian) | Requiere aprobación legal/compliance antes de código |
| **DECIDIR** | Punto abierto sin decisión documentada (ej. algoritmo matching, precision decimal, timezone canonical) | Marcar en ADR o issue; no asumir default |

---

## 7. Reglas de Cambio de Estado

1. **Solo el agente `qa-engineer` (o revisión humana documentada) puede mover `PENDIENTE` → `IMPLEMENTADO`/`PARCIAL`/`MOCK`**.
2. **Nunca** mover directamente a `IMPLEMENTADO` sin tests automatizados pasando en CI.
3. **Nunca** declarar `IMPLEMENTADO` un componente que depende de `REQUIERE PROVEEDOR`/`REQUIERE LICENCIA` sin que la dependencia esté resuelta y contractualizada.
4. Cambios de estado se registran en `CHANGELOG.md` con fecha, autor, PR/commit, y link a evidencia (CI run, test report, video).
5. Al cerrar cada fase, esta tabla se actualiza y versiona como `S-mvp-scope-v{phase}.md`.

---

## 8. Decisiones Pendientes (DECIDIR)

| Tema | Pregunta | Dónde se Resuelve |
|------|----------|-------------------|
| Precision decimal por defecto | `NUMERIC(38,18)` global o por moneda? | ADR-0006 / `docs/adr/0006-money-decimal.md` |
| Timezone canónico almacenamiento | UTC only (sí) pero presentación: tz usuario vs tz mercado? | `DECIDIR` (ADR pendiente: timezone/presentación) |
| Símbolos demo (formato, precisión, horario) | `EURUSD` vs `EUR/USD` vs `EURUSD.pro`; 5 vs 3 decimales; sesión 24/5 vs 24/7 | `docs/phase0/P-event-catalog.md` + ADR pendiente |
| Algoritmo matching demo | FIFO simple, price-time, pro-rata? | `DECIDIR` (ADR pendiente: matching engine) |
| Fee model demo | Spread-only, commission per lot, swap points? | `DECIDIR` (ADR pendiente: fee model) |
| Margin model demo | Reg T, portfolio margin, fixed %? | `DECIDIR` (ADR pendiente: margin model) |
| Retención audit log | 7 años (regulatorio) vs 30d (operativo)? | `DECIDIR` + legal review (no se afirma plazo legal) |
| Password policy (longitud, complejidad, breached check) | NIST 800-63B vs custom? | ADR-0008 + comprobación de contraseñas filtradas `REQUIERE PROVEEDOR` |
| Session concurrency limit | 1 sesión activa vs N? Revocación en login nuevo? | ADR-0008 |

---

> **Nota**: Este documento es **vivo**. Se actualiza al cerrar cada fase con evidencia real. No refleja aspiraciones, solo estado verificable.