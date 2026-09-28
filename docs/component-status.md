# Estado de componentes — clasificación

Fecha de verificación: 2026-09-28 · Fase 0 + Fase 1 (foundation)
Proyecto: `[PROJECT_NAME]` · Fuente de verdad de decisiones: `docs/phase0/00-decisions.md`

Leyenda:
`IMPLEMENTADO` (funciona y está verificado) · `PARCIAL` (existe pero incompleto) ·
`MOCK` (simulado) · `PENDIENTE` (no empezado) · `REQUIERE PROVEEDOR` ·
`REQUIERE LICENCIA/REGULACIÓN` · `REQUIERE DECISIÓN`

Evidencia de verificación (2026-09-28): `uv run ruff check .` + `ruff format --check .` +
`mypy packages services` limpios; `uv run python tools/check_boundaries.py` y
`tools/export_openapi.py --check` verdes; `uv run pytest` → **70 passed (45 unit, 22
integration, 3 e2e)** contra PostgreSQL y Redpanda reales; `npm run lint/typecheck/build
--workspace apps/web` → correcto; `docker build` de las 3 imágenes → OK; gitleaks v8.30.1
→ 0 hallazgos (`.gitleaks.toml`); pip-audit → 0 vulnerabilidades conocidas; npm audit
pasa con `--audit-level=critical` (ver deuda 6); trivy CRITICAL → 0 en imagen identity;
`terraform init -backend=false` + `validate` → válido; `kubectl kustomize` base+dev →
renderiza; `docker compose … config` → OK; trazas OTel extremo a extremo verificadas
(servicio → collector → Tempo, `GET /api/search` devuelve traceIDs).

---

## 1. Núcleo y contratos

| Componente | Clasificación | Notas |
|---|---|---|
| `packages/platform-kernel` (config, errores RFC 9457, logging JSON, auth JWT+roles, tokens, `money` Decimal, rate limit, idempotencia, middleware request-id, métricas Prometheus, loop_factory Windows) | IMPLEMENTADO | mypy strict; tests unitarios; redacción de secretos en logs |
| Exportación **traces OpenTelemetry** desde servicios | IMPLEMENTADO | SDK en `platform_kernel/telemetry.py` (OTLP/HTTP, instrumentación FastAPI+httpx, propagación W3C `traceparent`); activo solo con `OTEL_ENDPOINT`; E2E verificado contra Tempo (REQ-057) |
| `packages/platform-contracts` (roles, envelope de eventos, headers internos, esquemas de audit) | IMPLEMENTADO | 9 eventos del catálogo Fase 1 implementados |
| OpenAPI por servicio (`platform-contracts/openapi/*.yaml`) + tests de contrato | PARCIAL | Specs canónicos exportados (`tools/export_openapi.py`, gate `--check` en CI, `test_openapi_sync`); falta test productor/consumidor en runtime |
| `platform-contracts/CHANGELOG.md` de contratos | IMPLEMENTADO | 0.1.0 (Fase 1) |

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
| Compose local: PostgreSQL 17 (puerto **5433**), Redis 7, initdb con `platform_identity`/`platform_audit`/`platform_gateway` | IMPLEMENTADO | Healthy; todos los puertos de datos/obs enlazan a `127.0.0.1` (evita `localhost`→`::1`, que en Windows+Docker tarda ~2 s por conexión); psycopg exige SelectorEventLoop (mitigado en kernel + `loop_factory`) |
| Migraciones Alembic por servicio (schema propio, upgrade/downgrade) | IMPLEMENTADO | Commit explícito en `env.py` (evita autobegin); fix `path_separator` |
| Redpanda (perfil `events`) + pipeline outbox | IMPLEMENTADO | Relay en `identity/outbox.py` (reintentos con backoff exp+jitter, DLQ `dlq.<topic>`, métricas de backlog/publicados/DLQ, migración `0002_outbox_relay`) → consumidor `audit/consumer.py` (grupo `audit-service`, commit tras insert, dedup `event_id`) |
| Dockerfiles multi-stage non-root (gateway/identity/audit) | IMPLEMENTADO | Imágenes construidas; smoke `/healthz` 200 con migraciones en imagen |
| Imágenes publicadas en registry | PENDIENTE | Referenciadas en K8s como `platform/<svc>:dev` |
| K8s base + overlay dev (kustomize, probes, securityContext, resources) | PARCIAL | `kubectl kustomize` renderiza; **NO aplicado** (Fase 1), secretos PLACEHOLDER (ADR-0020) |
| Migraciones como init job en K8s | PENDIENTE | Hoy auto-migrate solo en entornos local/test (N §8.6) |

## 4. Observabilidad

| Componente | Clasificación | Notas |
|---|---|---|
| Logs JSON estructurados con request_id/correlation_id y redacción | IMPLEMENTADO | Formato UTC Windows-safe |
| Métricas Prometheus por servicio (`/metrics`) + middleware | IMPLEMENTADO | Scrape configurado en `prometheus.yaml` |
| OTel Collector config (perfil `obs`) | IMPLEMENTADO | Pipelines: traces → Tempo, metrics → Prometheus `:8889`, logs → Loki (dormant hasta que servicios exporten logs OTel) |
| Prometheus + Grafana + Loki + Tempo + Alloy (perfil `obs`) | IMPLEMENTADO (compose) | Datasources provisionadas por UID (`prometheus`/`loki`/`tempo`); Alloy con docker_sd filtra contenedores `platform-*` → Loki (flujo verificado: `streams=1`) |
| Dashboard RED en Grafana + runbooks | PARCIAL | Dashboard `grafana/dashboards/red.json` provisionado (req rate, %5xx, p95, outbox backlog/DLQ); runbooks 01–03 + README; faltan reglas de alerta |
| Atributos/propagación OTel traces extremo a extremo | IMPLEMENTADO | `init_telemetry` + `instrument_app` en los 3 servicios + `traceparent` de salida; E2E verificado: batch de spans del servicio llega al collector y Tempo responde en `/api/search` (ADR-0013, REQ-057) |

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
| `.github/workflows/ci.yml` | IMPLEMENTADO | 6 jobs: `quality` (ruff/format/mypy/fronteras/OpenAPI), `test` (pytest con PostgreSQL+Redpanda efímeros), `web` (lint/typecheck/build), `security` (gitleaks+pip-audit+npm audit), `supply-chain` (docker build+SBOM syft+trivy CRITICAL), `infra` (terraform/kustomize/compose); actions pinnadas por SHA; **aún no ejecutado en GitHub (requiere push)** |
| dependabot + secret-scan + análisis de dependencias + SBOM/CVE | IMPLEMENTADO | `.github/dependabot.yml` (pip/npm/actions/docker); gitleaks con `.gitleaks.toml`; pip-audit vía `uv export`; npm audit (bloqueo a nivel crítico); syft SBOM como artefacto; trivy CRITICAL bloquea |
| Path filters por servicio | PARCIAL | Solo `paths-ignore` global de `docs/**`/`**/*.md`; filtros por servicio cuando haya más teams/paths (ADR de fase posterior) |
| CODEOWNERS y branch protection | REQUIERE DECISIÓN | No hay usernames/owners conocidos en el repo; requiere cuentas de GitHub (G-security §1.7) |
| Tests de contrato productor/consumidor | PENDIENTE | OpenAPI versionado ya existe; falta ejecutar contratos en runtime bidireccional |

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
6. Vulnerabilidades npm en `next` 15.5.x (1 high en `postcss` embebido + 1 moderate):
   el fix publicado es `next` 16.3.6 (**semver-major**); CI bloquea solo a nivel crítico
   (`npm audit --audit-level=critical`) y el upgrade se planifica como trabajo propio.
7. gitleaks: `tests/` está en la allowlist de `.gitleaks.toml` (fixtures no desplegables
   como `TEST_JWT_SECRET`); cualquier fixture nuevo en `tests/` queda cubierto por esa
   decisión y cualquier secreto real fuera de `tests/` sigue bloqueando CI.
8. CODEOWNERS + branch protection: pendiente de decisión (no hay usernames/owners).
9. Self-telemetry del collector no publicada: `:8888` sin mapear en compose y `:8889`
   (exporter prometheus) queda vacío mientras ningún emisor envíe OTLP metrics; las
   métricas de negocio `platform_*` sí llegan por scrape directo de cada servicio.
10. Windows + `localhost` → `::1` cuesta ~2 s por conexión a puertos con publicación
    IPv4 de Docker; todos los defaults locales ya usan `127.0.0.1` — no reintroducir
    `localhost` en DSNs ni URLs de servicio (ver `.env.example`).
