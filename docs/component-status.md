# Estado de componentes — clasificación

Fecha de verificación: 2026-09-28 · Fase 0 + Fase 1 (foundation)
Proyecto: `[PROJECT_NAME]` · Fuente de verdad de decisiones: `docs/phase0/00-decisions.md`

Leyenda:
`IMPLEMENTADO` (funciona y está verificado) · `PARCIAL` (existe pero incompleto) ·
`MOCK` (simulado) · `PENDIENTE` (no empezado) · `REQUIERE PROVEEDOR` ·
`REQUIERE LICENCIA/REGULACIÓN` · `REQUIERE DECISIÓN`

Evidencia de verificación: `uv run ruff check .` + `ruff format --check .` + `mypy packages services`
limpios; `uv run pytest` → **52 passed (30 unit, 19 integration, 3 e2e), 0 warnings**;
`npm run build/lint/typecheck --workspace apps/web` → correcto; `docker build` de las 3
imágenes → OK; smoke de imagen identity/audit → `/healthz` 200; `kubectl kustomize base` → renderiza.

---

## 1. Núcleo y contratos

| Componente | Clasificación | Notas |
|---|---|---|
| `packages/platform-kernel` (config, errores RFC 9457, logging JSON, auth JWT+roles, tokens, `money` Decimal, rate limit, idempotencia, middleware request-id, métricas Prometheus, loop_factory Windows) | IMPLEMENTADO | mypy strict; tests unitarios; redacción de secretos en logs |
| Exportación **traces OpenTelemetry** desde servicios | PENDIENTE | Existe ADR-0013 y `instrumentation.ts` stub; falta SDK OTel en Python (Fase posterior) |
| `packages/platform-contracts` (roles, envelope de eventos, headers internos, esquemas de audit) | IMPLEMENTADO | 9 eventos del catálogo Fase 1 implementados |
| OpenAPI por servicio (`platform-contracts/openapi/*.yaml`) + tests de contrato | PENDIENTE | FastAPI genera `/docs` en local; contrato versionado y gates de CI en Fase posterior |
| `platform-contracts/CHANGELOG.md` de contratos | PENDIENTE | Requerido al primer cambio de contrato |

## 2. Servicios Fase 1

| Componente | Clasificación | Notas |
|---|---|---|
| `identity` — registro, verificación de email, login/refresh con rotación + detección de reuso, sesiones, logout/revocación, forgot/reset, MFA TOTP (enable/disable/verify), RBAC, rate limits, outbox | IMPLEMENTADO | Suite integration + e2e verdes |
| Envío real de email (verificación / reset) | REQUIERE PROVEEDOR | Hoy: persistido en `email_outbox` + evento; sin SMTP/provider (Fase posterior) |
| `audit` — ingesta batch append-only, RBAC por token de servicio, dedup por `event_id`, filtros + cursor, bloqueo de UPDATE/DELETE | IMPLEMENTADO | Append-only verificado por trigger/listener |
| `gateway` — proxy con validación JWT, headers de seguridad, request-id/correlation, rate limit, passthrough problem+json, `/healthz` agregado y `/readyz` | IMPLEMENTADO | `/healthz` devuelve 503 si upstreams caídos (agregado, por diseño) |
| Devices/sesiones persistentes multi-dispositivo avanzado | PENDIENTE | Tablas de sesión existentes; fingerprint de dispositivo no implementado |

## 3. Datos e infraestructura

| Componente | Clasificación | Notas |
|---|---|---|
| Compose local: PostgreSQL 17 (puerto **5433**), Redis 7, initdb con `platform_identity`/`platform_audit`/`platform_gateway` | IMPLEMENTADO | Healthy; notas Windows: servicio nativo de PG ocupa 5432; psycopg exige SelectorEventLoop (mitigado en kernel + `loop_factory`) |
| Migraciones Alembic por servicio (schema propio, upgrade/downgrade) | IMPLEMENTADO | Commit explícito en `env.py` (evita autobegin); fix `path_separator` |
| Redpanda (perfil `events`) | IMPLEMENTADO (compose) | Sin consumidores/productores todavía (outbox → audit va por HTTP en Fase 1) |
| Dockerfiles multi-stage non-root (gateway/identity/audit) | IMPLEMENTADO | Imágenes construidas; smoke `/healthz` 200 con migraciones en imagen |
| Imágenes publicadas en registry | PENDIENTE | Referenciadas en K8s como `platform/<svc>:dev` |
| K8s base + overlay dev (kustomize, probes, securityContext, resources) | PARCIAL | `kubectl kustomize` renderiza; **NO aplicado** (Fase 1), secretos PLACEHOLDER (ADR-0020) |
| Migraciones como init job en K8s | PENDIENTE | Hoy auto-migrate solo en entornos local/test (N §8.6) |

## 4. Observabilidad

| Componente | Clasificación | Notas |
|---|---|---|
| Logs JSON estructurados con request_id/correlation_id y redacción | IMPLEMENTADO | Formato UTC Windows-safe |
| Métricas Prometheus por servicio (`/metrics`) + middleware | IMPLEMENTADO | Scrape configurado en `prometheus.yaml` |
| OTel Collector config (perfil `obs`) | IMPLEMENTADO | Archivo creado y validado por `docker compose config` |
| Prometheus + Grafana (perfil `obs`) | IMPLEMENTADO (compose) | Grafana sin datasource provisioning automático (manual en Fase 1) |
| Dashboards RED/SLO, reglas de alerta, runbooks | PENDIENTE | `infrastructure/monitoring/` solo tiene collector+prometheus |
| Atributos/propagación OTel traces extremo a extremo | PENDIENTE | ADR-0013 define la dirección; implementación posterior |

## 5. Frontend

| Componente | Clasificación | Notas |
|---|---|---|
| `apps/web` shell Next.js 15 (App Router, TS estricto, Tailwind 4, PWA manifest, i18n `es`/`en` tipado, RTL preparado) | IMPLEMENTADO | build/lint/typecheck verdes |
| Login/registro contra gateway (flujo real con tokens) | MOCK | Formulario en estado mock, sin `fetch`; marcado en UI |
| Trading UI, catálogo de símbolos, depósitos | PENDIENTE | Fases 3–6 |
| `apps/admin-shell` (backoffice) | PENDIENTE | Fase 7 |
| Service Worker / offline completo | PENDIENTE | Manifest listo; SW con PWA completa |

## 6. CI/CD y gobernanza

| Componente | Clasificación | Notas |
|---|---|---|
| `.github/workflows/ci.yml` (ruff/format/mypy + pytest con PostgreSQL efímero y creación de DBs por servicio) | IMPLEMENTADO | Sin ejecución real en GitHub aún (repo sin remote) |
| Path filters por servicio, CODEOWNERS, dependabot, secret-scan, SBOM | PENDIENTE | Previstos en `M-tech-stack.md` §11 / `N-monorepo-structure.md` |
| Tests de contrato productor/consumidor | PENDIENTE | Requiere OpenAPI versionado |
| Análisis de dependencias (pip-audit, npm audit) en CI | PENDIENTE | — |

## 7. Dominio de negocio (roadmap por fases)

| Componente | Clasificación |
|---|---|
| Ledger double-entry, wallet, cuentas de trading (Fase 2) | PENDIENTE |
| Market data adapters + streaming WS (Fase 3) | PENDIENTE |
| Trading OMS/EMS, posiciones, margin, risk (Fase 4) | PENDIENTE |
| Pagos (depósitos/retiros) | REQUIERE PROVEEDOR (adapters de pago) |
| KYC/AML | REQUIERE PROVEEDOR (proveedor de verificación) + REQUIERE DECISIÓN (alcance jurisdiccional) |
| Operar en vivo (live trading, capital real) | REQUIERE LICENCIA/REGULACIÓN — `FLAG_LIVE_TRADING=false` forzado por código (ADR-0012) |
| Identidad de marca/dominio (`[PROJECT_NAME]`, `[BRAND_NAME]`, `[DOMAIN]`) | REQUIERE DECISIÓN (Producto/Legal) |
| Locales restantes más allá de `es`/`en` (ADR-0015, 7 idiomas) | REQUIERE DECISIÓN (conjunto definitivo) |

---

## Deudas técnicas conocidas (Fase 1)

1. Rate limits se prueban a nivel unitario (fixtures relajan límites para la suite).
2. `clean_dbs` dropea schemas de la base local entre sesiones de prueba (por diseño en dev).
3. e2e usa puertos fijos 18080/18081/18083 con espera de liberación; en paralelismo futuro
   habrá que parametrizar por `worker_id` (pytest-xdist).
4. Comentario de `N-monorepo-structure.md` menciona `pnpm-lock.yaml`; el repo usa **npm
   workspaces** (decisión válida de N §4.2 — pnpm no disponible en la máquina).
5. `uv sync` a secas (modo exact) desinstala los miembros del workspace; instalar con
   `uv sync --all-packages` (documentado en README y CI).
