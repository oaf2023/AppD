# F — C4 Containers Diagram

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)

## 1. Diagrama C4 Containers (Mermaid)

```mermaid
C4Container
title Diagrama de Contenedores — [PROJECT_NAME] (Fase 1 vs Fase 2+)

Person(customer, "Cliente / Trader", "Navegador / PWA")
Person(admin_user, "Admin / Backoffice", "Navegador")

System_Boundary(system, "[PROJECT_NAME] — Plataforma FinTech/Trading OTC") {

    %% ==================== FASE 1 (EXISTENTE TRAS ESTA FASE) ====================
    Container_Boundary(phase1, "Fase 1 — Foundation (EXISTENTE TRAS FASE 1)") {

        Container(web, "apps/web", "Next.js 15, React, TypeScript, Tailwind, PWA",
            "SPA/SSR pública: landing, registro, login, dashboard demo, trading UI, account, settings. SSR/SSG para SEO, i18n/RTL, Service Worker offline-first.")

        Container(admin_shell, "apps/admin-shell", "Next.js 15, React, TypeScript, Tailwind",
            "Shell de backoffice (micro-frontend host). Carga remota de MFEs de admin. Autenticación admin, RBAC, auditoría visible.")

        Container(gateway, "services/gateway", "Python 3.13, FastAPI",
            "Único entrypoint externo (HTTPS/WSS). Terminación TLS, routing, validación JWT, rate limit, security headers, request-id, correlación OTel, circuit breaker básico. NO lógica de negocio.")

        Container(identity, "services/identity", "Python 3.13, FastAPI",
            "Usuarios, credenciales (Argon2id), sesiones, MFA TOTP, refresh tokens rotativos con detección de reuso, RBAC, devices, login history, account recovery. Emite eventos de dominio.")

        Container(audit, "services/audit", "Python 3.13, FastAPI",
            "Log append-only inmutable de acciones críticas (consumidor de eventos). Escribe en su propio schema PostgreSQL. Índices por correlation_id, aggregate_id, timestamp. Retención configurable.")
    }

    %% ==================== FASE 2+ (PENDIENTE) ====================
    Container_Boundary(phase2plus, "Fase 2+ — PENDIENTE (no existen en Fase 1)") {

        Container(accounts, "services/accounts", "Python 3.13, FastAPI",
            "Cuentas de trading, perfiles, jurisdicción, límites, estado (active/suspended/closed), metadata KYC. [PENDIENTE]")

        Container(wallet, "services/wallet", "Python 3.13, FastAPI",
            "Balances multi-moneda (vista/proyección verificada contra ledger). No es fuente de verdad. [PENDIENTE]")

        Container(ledger, "services/ledger", "Python 3.13, FastAPI",
            "Double-entry append-only, fuente de verdad financiera. Asientos inmutables, conciliación, auditoría contable. [PENDIENTE]")

        Container(market_data, "services/market-data", "Python 3.13, FastAPI",
            "Adapters de proveedores, normalización, cache, streaming WebSocket (ticks, candles, order book). [PENDIENTE]")

        Container(trading, "services/trading", "Python 3.13, FastAPI",
            "OMS/EMS: órdenes, ejecución, posiciones, margen, PnL en tiempo real, SL/TP, motor de matching interno (demo). [PENDIENTE]")

        Container(risk, "services/risk", "Python 3.13, FastAPI",
            "Límites pre-trade/post-trade, circuit breakers, kill switches, margin calls, exposure aggregation. [PENDIENTE]")

        Container(payments, "services/payments", "Python 3.13, FastAPI",
            "Depósitos/retiros vía adapters desacoplados (PSP, crypto, bank). Idempotencia, webhooks, reconciliation. [PENDIENTE]")

        Container(kyc, "services/kyc", "Python 3.13, FastAPI",
            "Orquestación KYC/AML con adapters de proveedor. Decision engine, document verification, ongoing monitoring. [PENDIENTE]")

        Container(notification, "services/notification", "Python 3.13, FastAPI",
            "Email/SMS/push/in-app/webhook via adapters. Plantillas, preferencias, dedup, rate limit. [PENDIENTE]")

        Container(admin, "services/admin", "Python 3.13, FastAPI",
            "Backoffice BFF: agrega datos de identity, accounts, wallet, ledger, trading, risk, kyc, audit para MFEs de admin-shell. [PENDIENTE]")
    }
}

%% Infraestructura (compartida)
ContainerDb(postgres, "PostgreSQL 17", "Una BD lógica; schemas aislados por servicio",
    "Schemas: identity, audit, accounts, wallet, ledger, market_data, trading, risk, payments, kyc, notification, admin. Sin acceso cruzado a tablas.")

ContainerDb(redis, "Redis 7", "Cache, sesiones, rate-limit, pub/sub ligero",
    "TTL por caso de uso. Cluster mode en producción. [PENDIENTE: Redis Sentinel/Cluster config]")

ContainerQueue(redpanda, "Redpanda", "Log de eventos duradero (API Kafka compat)",
    "Topics versionados por evento. Retención 7d (config). Transactional outbox en cada servicio. [PENDIENTE: mirroring cross-region]")

Container(otel, "OTel Collector", "OpenTelemetry Collector",
    "Receiver: OTLP (gRPC/HTTP). Processor: batch, memory_limiter, span filtering. Exporter: Prometheus, Loki, Tempo. [PENDIENTE: config producción]")

Container(prom, "Prometheus + Grafana", "Métricas + Dashboards",
    "Scrape: gateway, identity, audit, (futuros servicios). Alertas: SLO/SLI, error budget, latencia p99, tasa error 5xx. [PENDIENTE: reglas completas]")

Container(loki, "Loki", "Logs agregados",
    "Labels: service, environment, level, trace_id. Retención 30d. [PENDIENTE: retention policies]")

Container(tempo, "Tempo", "Trazas distribuidas",
    "TraceID propagado via W3C traceparent. Muestreo adaptativo. [PENDIENTE: sampling config]")

Container(s3, "Object Storage (S3-compatible)", "Placeholder REQUIERE PROVEEDOR",
    "Documentos KYC, reportes, statements, backups. [REQUIERE PROVEEDOR en Fase 1]")

%% Relaciones
Rel(customer, web, "HTTPS/WSS", "Next.js PWA")
Rel(admin_user, admin_shell, "HTTPS/WSS", "Admin shell")

Rel(web, gateway, "HTTPS/WSS", "Todas las peticiones API/WS")
Rel(admin_shell, gateway, "HTTPS/WSS", "Todas las peticiones API/WS")

Rel(gateway, identity, "HTTP/JSON (sync)", "Validar JWT, introspect token, login, register, MFA, refresh")
Rel(gateway, audit, "HTTP/JSON (sync)", "Health, readiness (audit no expone API de negocio)")

Rel_Back(gateway, redpanda, "Produce events (async)", "Request/response logs, security events")

Rel(identity, postgres, "SQL (asyncpg/SQLAlchemy)", "Schema: identity")
Rel(audit, postgres, "SQL (asyncpg/SQLAlchemy)", "Schema: audit")

Rel(identity, redis, "Redis protocol", "Sesiones, rate-limit, cache tokens revocados")
Rel(gateway, redis, "Redis protocol", "Rate limit global, cache JWKS, revocation list")

Rel(identity, redpanda, "Produce (outbox)", "UserRegistered, UserLoggedIn, MFAEnabled, PasswordChanged, DeviceAdded")
Rel(audit, redpanda, "Consume", "Todos los eventos de dominio para log inmutable")

Rel(phase2plus, postgres, "SQL (asyncpg/SQLAlchemy)", "Schemas propios por servicio")
Rel(phase2plus, redis, "Redis protocol", "Cache, pub/sub, rate-limit por servicio")
Rel(phase2plus, redpanda, "Produce/Consume (outbox)", "Eventos de dominio versionados")

Rel(otel, prom, "OTLP metrics", "Métricas")
Rel(otel, loki, "OTLP logs", "Logs")
Rel(otel, tempo, "OTLP traces", "Trazas")
Rel(gateway, otel, "OTLP", "Traces, metrics, logs")
Rel(identity, otel, "OTLP", "Traces, metrics, logs")
Rel(audit, otel, "OTLP", "Traces, metrics, logs")
Rel(phase2plus, otel, "OTLP", "Traces, metrics, logs")

Rel(phase2plus, s3, "S3 API", "PUT/GET objetos (KYC docs, statements)")
```

## 2. Tabla de Comunicación entre Contenedores

| Origen | Destino | Protocolo | Formato | Autenticación | Puertos (interno) | Fase | Notas |
|--------|---------|-----------|---------|---------------|-------------------|------|-------|
| Cliente (navegador) | `apps/web` | HTTPS/WSS | HTML/JSON/WS | Ninguna (público) / Cookie HttpOnly (auth) | 443 (ext) → 3000 (int) | 1 | PWA, Service Worker |
| Admin (navegador) | `apps/admin-shell` | HTTPS/WSS | HTML/JSON/WS | Cookie HttpOnly (admin) | 443 (ext) → 3001 (int) | 1 | Shell MFE host |
| `apps/web` | `gateway` | HTTPS/WSS | JSON / WS (JSON) | JWT Access Token (Bearer) | 443 (ext) → 8000 (int) | 1 | Único entrypoint |
| `apps/admin-shell` | `gateway` | HTTPS/WSS | JSON / WS (JSON) | JWT Access Token (Bearer, scope admin) | 443 (ext) → 8000 (int) | 1 | Único entrypoint |
| `gateway` | `identity` | HTTP/JSON (sync) | JSON | Service JWT (mTLS opcional Fase 2+) | 8000 → 8001 | 1 | Validar token, login, register, refresh, MFA |
| `gateway` | `audit` | HTTP/JSON (sync) | JSON | Service JWT | 8000 → 8002 | 1 | Solo health/readiness |
| `gateway` | `redpanda` | Kafka protocol (async) | Avro/JSON (schema registry) | SASL/SCRAM (producer) | 8000 → 9092 | 1 | Request/response logs, security events |
| `identity` | `postgres` | PostgreSQL wire | SQL (asyncpg) | Usuario BD por servicio | 8001 → 5432 | 1 | Schema `identity` |
| `audit` | `postgres` | PostgreSQL wire | SQL (asyncpg) | Usuario BD por servicio | 8002 → 5432 | 1 | Schema `audit` |
| `identity` | `redis` | RESP3 | Redis commands | ACL user `identity` | 8001 → 6379 | 1 | Sesiones, rate-limit, revocation |
| `gateway` | `redis` | RESP3 | Redis commands | ACL user `gateway` | 8000 → 6379 | 1 | Rate limit global, JWKS cache |
| `identity` | `redpanda` | Kafka protocol (async) | Avro/JSON | SASL/SCRAM (producer) | 8001 → 9092 | 1 | Outbox → eventos de dominio |
| `audit` | `redpanda` | Kafka protocol (async) | Avro/JSON | SASL/SCRAM (consumer) | 8002 → 9092 | 1 | Consumer group `audit-service` |
| `services/*` (Fase 2+) | `postgres` | PostgreSQL wire | SQL (asyncpg) | Usuario BD por servicio | 800x → 5432 | 2+ | Schema propio por servicio |
| `services/*` (Fase 2+) | `redis` | RESP3 | Redis commands | ACL user por servicio | 800x → 6379 | 2+ | Cache, pub/sub, rate-limit |
| `services/*` (Fase 2+) | `redpanda` | Kafka protocol (async) | Avro/JSON | SASL/SCRAM (producer/consumer) | 800x → 9092 | 2+ | Outbox + consumers |
| `services/*` | `otel` | OTLP (gRPC/HTTP) | Protobuf | Ninguna (red interna) | 800x → 4317/4318 | 1/2+ | Traces, metrics, logs |
| `services/*` (Fase 2+) | `s3` | S3 API (HTTPS) | Multipart/JSON | IAM role / Access Key (IRSA) | 800x → 443/9000 | 2+ | Documentos, reportes |

## 3. Responsabilidades por Contenedor

| Contenedor | Responsabilidad Principal | Por qué existe separado |
|------------|--------------------------|------------------------|
| `apps/web` | Presentación pública, PWA, SSR/SSG, i18n | Separación cliente/servidor; despliegue independiente; SEO; offline-first |
| `apps/admin-shell` | Host MFE backoffice, auth admin, RBAC UI | Ciclo de vida y despliegue distinto al frontend público; aislamiento de superficie de ataque |
| `gateway` | **Único entrypoint externo**: TLS termination, routing, JWT validation, rate limit, security headers, request-id, OTel correlation, circuit breaker | **Single choke point** para seguridad, observabilidad, gobernanza de APIs, versionado, canary releases. Evita acoplamiento cliente→servicios internos. Permite cambiar servicios sin romper clientes. |
| `identity` | Usuarios, authN, authZ, sesiones, MFA, devices, RBAC | Dominio acotado (Identity & Access); ciclo de vida propio; escalado independiente (picos de login); cumplimiento seguridad (Argon2id, refresh rotation) |
| `audit` | Log inmutable append-only de eventos críticos | Requisito regulatorio/auditoría; inmutabilidad estricta; consumidor pasivo (no emite comandos); retención legal distinta |
| `accounts` | Cuentas trading, perfiles, jurisdicción, límites | Bounded context "Account Management"; datos maestros de cliente; requisitos KYC/regulatorios propios |
| `wallet` | Balances multi-moneda (proyección verificada) | Vista de solo lectura optimizada para UI; no es fuente de verdad; desacopla consultas de ledger |
| `ledger` | Double-entry append-only, fuente de verdad financiera | **Núcleo contable**; inmutabilidad absoluta; consistencia ACID; conciliación; auditoría financiera |
| `market-data` | Adapters, normalización, streaming WS | Acoplamiento a proveedores externos volátiles; normalización canónica; cache agresivo; streaming de alta frecuencia |
| `trading` | OMS/EMS, órdenes, posiciones, margen, PnL, SL/TP | Dominio de trading puro; latencia crítica; reglas de negocio complejas; motor de matching (demo) |
| `risk` | Límites pre/post-trade, circuit breakers, kill switches | Transversal de seguridad financiera; evaluación síncrona en camino crítico; independencia de trading |
| `payments` | Depósitos/retiros vía adapters | Integración con PSP/bancos/crypto; idempotencia/webhooks; reconciliación; compliance AML |
| `kyc` | Orquestación KYC/AML con adapters | Proveedores variables; decision engine; ongoing monitoring; regulación cambiante |
| `notification` | Multi-canal (email/SMS/push/in-app/webhook) | Adapters desacoplados; plantillas; preferencias; dedup; rate limit por canal |
| `admin` | Backoffice BFF (agregación para MFEs) | Evita N+1 desde shell; shape de datos para UI admin; autorización granular admin |

## 4. Por qué `gateway` es el Único Entrypoint Externo

1. **Superficie de ataque mínima**: Un solo punto de terminación TLS, validación de certificados, WAF futuro, DDoS protection.
2. **Contrato único versiónado**: OpenAPI en gateway; clientes no acoplan a servicios internos (evita breaking changes cascada).
3. **Seguridad centralizada**: JWT validation, rate limit global y por cliente, security headers (CSP, HSTS, COOP/COEP), IP allow/deny, request-id obligatorio.
4. **Observabilidad unificada**: Todas las peticiones generan trace OTel desde el gateway; correlación `trace_id`/`span_id` propagada a todos los servicios.
5. **Gobernanza de APIs**: Versionado (`/v1/`, `/v2/`), deprecación controlada, canary/blue-green routing, feature flags por ruta.
6. **Resiliencia**: Circuit breaker, timeout, retry policies, bulkhead por servicio downstream; fallback graceful (ej. mercado caído → cached prices).
7. **Auditoría completa**: Request/response logging estructurado en Redpanda para replay, compliance, debugging.
8. **Cumplimiento**: Un solo lugar para data residency, logging de acceso, consentimiento, GDPR/CCPA article 30 records.

## 5. Leyenda de Estado

| Etiqueta | Significado |
|----------|-------------|
| **EXISTENTE TRAS FASE 1** | Implementado, testeado, desplegable en compose/K8s al cierre de Fase 1 |
| **PENDIENTE** | Diseñado en Fase 0; implementación autorizada en fase futura |
| **REQUIERE PROVEEDOR** | Dependencia externa no resuelta (S3, Vault, KYC provider, PSP, market data feed) |
| **REQUIERE LICENCIA/REGULACIÓN** | Bloqueado legalmente hasta licencia/autorización regulatoria (LIVE trading) |
| **DECIDIR** | Punto abierto que requiere decisión explícita (no asumir default) |

---

> **Nota**: Este diagrama refleja el estado **objetivo al cierre de la Fase 1** (contenedores fase 1 = existentes; fase 2+ = pendientes). Los puertos internos son referenciales para docker-compose; en Kubernetes usan `Service` + `NetworkPolicy`.