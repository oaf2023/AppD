# 00 — DECISIONES CANÓNICAS (fuente de verdad de la Fase 0)

Fecha: 2026-09-27
Estado: APROBADO POR USUARIO (plan de ejecución Fase 0 + Fase 1)

Todos los documentos de `docs/phase0/` y `docs/adr/` deben ser consistentes con este archivo. En caso de conflicto, este documento prevalece hasta que se actualice mediante ADR nuevo.

## 1. Identidad (nombre y marca definidos; dominio pendiente)

- `PROJECT_NAME` = `MonedasAR`
- `DOMAIN` = `[DOMAIN]`
- `BRAND_NAME` = `MonedasAR`

Nombre y marca (`MonedasAR`) decididos por Producto el 2026-09-28 y propagados a código, imágenes Docker, Títulos OpenAPI y documentación. `DOMAIN` sigue literal `[DOMAIN]`: ningún dominio TLS, CSP, certificado ni declaración legal se da por existente hasta su definición por Legal.

## 2. Referencia funcional

El sistema se diseña con **paridad funcional de categorías, workflows y principios arquitectónicos** respecto de una plataforma de referencia de derivados OTC (Deriv.com), **sin** copiar código, activos gráficos, textos protegidos, secretos, credenciales, nombres comerciales ni identidad visual.

## 3. Descomposición: microservicios desde el inicio (decisión del usuario)

Catálogo mínimo obligatorio:

| Servicio | Responsabilidad | Fase |
|---|---|---|
| `gateway` | edge: routing, validación JWT, rate limit, headers seguridad, request-id | 1 |
| `identity` | usuarios, credenciales, sesiones, MFA, RBAC, devices, login history | 1 |
| `audit` | log append-only de acciones críticas (consumidor de eventos) | 1 |
| `accounts` | cuentas de trading, perfiles, jurisdicción | 2 |
| `wallet` | balances multi-moneda (vista, no fuente de verdad) | 2 |
| `ledger` | double-entry, append-only, fuente de verdad financiera | 2 |
| `market-data` | adapters, normalización, streaming WS (adelanto F1: snapshot overview keyless, 2026-09-28) | 3 |
| `trading` | OMS, EMS, posiciones, margin, PnL | 4 |
| `risk` | límites, circuit breakers, kill switches | 4 |
| `payments` | depósitos/retiros vía adapters | 6 |
| `kyc` | orquestación KYC/AML con adapters de proveedor | 6 |
| `notification` | email/SMS/push/in-app/webhook (adapters) | 2+ |
| `admin` | backoffice BFF | 7 |

Criterios de creación de un nuevo servicio (ADR-0002): (1) límite de dominio distinto con ciclo de vida propio, (2) requisito de escalado independiente medible, (3) tolerancia a fallos que no puede ser global, o (4) equipo/proceso independiente. **Nunca** por moda.

Cada servicio: schema PostgreSQL propio (`identity`, `audit`, ...), sin acceso cruzado a tablas, comunicación solo por API versionada + eventos, sin joins entre servicios.

## 4. Stack definitivo (Fase 1)

| Capa | Tecnología | Justificación |
|---|---|---|
| Frontend | Next.js 15 (App Router), React, TypeScript, Tailwind CSS, PWA | SSR/SSG para SEO público, ecosistema, i18n/RTL |
| Backend | Python 3.14 (original 3.13; upgrade BUILD-024, ADR-0018), FastAPI, Pydantic v2, SQLAlchemy 2 async, asyncio | requisito del prompt; ecosistema cuantitativo/data |
| Latencia crítica | **Sin Rust/Go en Fase 1**; se reintenta solo con benchmark que lo justifique (ADR-0003) | evitar lenguaje adicional sin evidencia |
| Base transaccional | PostgreSQL 17 | ACID para dinero |
| Cache/sesión/rate-limit | Redis 7 | patrones simples y probados |
| Eventos | Redpanda (API Kafka) | log duradero, reintentos, compatibilidad Kafka |
| Object storage | S3-compatible (placeholder `REQUIERE PROVEEDOR` en Fase 1) | documentos KYC, reportes |
| Mensajería ligera interna | HTTP/JSON síncrono + Redpanda asíncrono | sin malla de servicios en Fase 1 |
| Infra | Docker, docker-compose (local), Kubernetes manifests (preparados), Terraform (estructura) | portabilidad |
| CI/CD | GitHub Actions | integración nativa con monorepo |
| Observabilidad | OpenTelemetry, Prometheus, Grafana, Loki, Tempo | estándar abierto |
| Secrets | env en local; Vault/KMS `REQUIERE PROVEEDOR` en producción | sin secretos en repo |

## 5. Dinero y consistencia

- Nunca `float`. Montos en `NUMERIC(38,18)` en PostgreSQL y `decimal.Decimal` en Python; para monedas con unidad mínima se almacena también `amount_minor BIGINT` cuando la moneda lo permite.
- El **Ledger** es la única fuente de verdad de saldos; los balances de `wallet` son proyecciones verificables.
- Consistencia fuerte en dinero (transacciones ACID + outbox para eventos). Eventual consistency solo en analytics/reporting.
- Idempotencia obligatoria en orders, payments, withdrawals, deposits, webhooks y ledger postings (`Idempotency-Key` + hash de solicitud + respuesta almacenada).

## 6. DEMO vs LIVE

- Dos modos explícitos: `DEMO` y `LIVE`.
- `LIVE` está implementado como código **deshabilitado por defecto** (`feature_flag live_trading = false`) y bloqueado por gating de fase: no se activa sin licencia, proveedor de ejecución, contratos y aprobación legal.
- Todo dato simulado se etiqueta como tal; prohibido presentar datos simulados como reales.
- Cualquier componente se clasifica como: `IMPLEMENTADO`, `PARCIAL`, `MOCK`, `PENDIENTE`, `REQUIERE PROVEEDOR`, `REQUIERE LICENCIA/REGULACIÓN`.

## 7. Seguridad (invariantes no negociables)

- Passwords: Argon2id (obligatorio, nunca texto plano ni hashes débiles).
- JWT de acceso corto (≤15 min) + refresh token rotativo con detección de reuso.
- MFA TOTP opcional por flag en Fase 1; passkeys/WebAuthn `PENDIENTE`.
- Sin IDs secuenciales públicos: UUIDv7/uco random en entidades expuestas.
- Webhooks: verificación de firma obligatoria; rate limiting por IP y cuenta.
- Nada de secretos en repo, logs, frontend ni documentación.
- Auditoría append-only con `correlation_id` y `request_id` en toda acción crítica.

## 8. Eventos

Catálogo versionado en `docs/phase0/P-event-catalog.md`. Envelope mínimo: `event_id`, `event_type`, `schema_version`, `aggregate_id`, `aggregate_type`, `timestamp` (UTC), `correlation_id`, `causation_id`, `producer`, `payload`. Publicación mediante **transactional outbox**.

## 9. Alcance de esta ejecución

- **Incluido**: Fase 0 (apartados A–Z) y Fase 1 (foundation: monorepo, CI/CD, identity, audit, gateway, DB, Redis, Redpanda, compose, frontend shell, observabilidad básica, tests).
- **Excluido**: todo lo demás hasta nueva autorización (Fases 2–9).

## 10. Regla de no-ficción

Ante ausencia de API, proveedor, licencia, feed, pasarela, KYC provider, liquidez, aprobación regulatoria, credencial cloud, secreto, certificado o contrato externo: **no se inventa**. Se crea interface + adapter + mock/sandbox + placeholder de configuración y se documenta exactamente qué falta. Ver `docs/phase0/X-blocked-to-live.md`.
