# Estado de componentes — clasificación

Fecha de verificación: 2026-09-28 · Fase 0 + Fase 1 (foundation)
Proyecto: `MonedasAR` · Fuente de verdad de decisiones: `docs/phase0/00-decisions.md`

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

Evidencia frontend + despliegue (2026-09-28): `npm run lint/typecheck/build` verdes;
E2E en navegador contra `http://192.168.1.200:40000` (landing → login → `/panel` con
`/me` real); BFF con cookies `HttpOnly` verificadas; pipeline outbox→Redpanda→
`audit.records` con 3 eventos (publicados, sin DLQ); stack OMV con 13 contenedores
`healthy` (perfil obs incluido) y Grafana `:40021` respondiendo 200.

Evidencia rename MonedasAR + portada (2026-09-28): rename completo de
`[PROJECT_NAME]`/`[BRAND_NAME]` → `MonedasAR` (61 + 36 apariciones, 51 archivos:
UI, títulos OpenAPI, manifests k8s, Terraform, docs; `[DOMAIN]` conservado como
marcador literal; el label `app.kubernetes.io/part-of` ahora cumple la regex de
Kubernetes); `ruff`/`format`/`mypy`/`fronteras`/`export_openapi --check` verdes;
`uv run pytest` → **70 passed**; `npm run lint/typecheck/build` verdes; E2E en
navegador local y contra `http://192.168.1.200:40000` → registro → login →
`/panel` → logout → relogin (`ok=true`, 0 errores de consola propios; aviso COOP
sobre HTTP LAN cosmético); redespliegue OMV con web+gateway+identity+audit
reconstruidos, contenedores `healthy` y `healthz` OK.

Evidencia sección Mercados + servicio `market-data` (2026-09-28): discovery de
proveedores keyless con verificación de ToS y de endpoints en vivo
(`docs/API_INTEGRATIONS.md`); servicio nuevo `services/market-data` con 4
adapters (Frankfurter→ECB, Kraken→CoinGecko), cache TTL, circuit breaker y
regla no-ficción (`stale`/`unavailable`, jamás precio inventado); contrato
`platform_contracts/market_data.py` + spec `openapi/market-data.yaml` con gate de
deriva; gateway con ruta pública y `/healthz` agregado (3 checks); gates
`ruff`/`format`/`mypy`/`fronteras`/`export_openapi --check` verdes;
`uv run pytest` → **78 passed (53 unit, 22 integration, 3 e2e)**; web
`lint`/`typecheck`/`build` verdes; `docker build` de la imagen `market-data` →
OK y smoke en contenedor: `/healthz` 200 y `/api/v1/market-data/overview` 200
con datos reales (`frankfurter` y `kraken`, valores > 0); `docker compose … config`
y `kubectl kustomize` → OK. E2E en navegador local (2026-09-28): portada
`http://localhost:3200` con stack local (web+gateway+market-data), sección
`#mercados` con Forex (EUR/GBP, EUR/JPY, EUR/USD con sello BCE) y Criptomonedas
(BTC/ETH/USDT con sello UTC vía Kraken) en badge `Disponible`, 5 cards
"Próximamente · Fases 3-4", `Fuente:` sin duplicados (fix de atribución en
`MarketClassCard`) y **0 errores de consola / 0 peticiones fallidas**; captura en
`/tmp` (mercados.png). CI en GitHub y redespliegue OMV: pendientes de
push/confirmación.

---

## 1. Núcleo y contratos

| Componente | Clasificación | Notas |
|---|---|---|
| `packages/platform-kernel` (config, errores RFC 9457, logging JSON, auth JWT+roles, tokens, `money` Decimal, rate limit, idempotencia, middleware request-id, métricas Prometheus, loop_factory Windows) | IMPLEMENTADO | mypy strict; tests unitarios; redacción de secretos en logs |
| Exportación **traces OpenTelemetry** desde servicios | IMPLEMENTADO | SDK en `platform_kernel/telemetry.py` (OTLP/HTTP, instrumentación FastAPI+httpx, propagación W3C `traceparent`); activo solo con `OTEL_ENDPOINT`; E2E verificado contra Tempo (REQ-057) |
| `packages/platform-contracts` (roles, envelope de eventos, headers internos, esquemas de audit, contrato de mercados `market_data.py`) | IMPLEMENTADO | 9 eventos del catálogo Fase 1 implementados; `MarketOverview`/`OverviewQuote` con `simulated: false` estructural (G3/X-07 bloqueado) |
| OpenAPI por servicio (`platform-contracts/openapi/*.yaml`) + tests de contrato | PARCIAL | 4 specs canónicos exportados (`tools/export_openapi.py`, gate `--check` en CI, `test_openapi_sync`); falta test productor/consumidor en runtime |
| `platform-contracts/CHANGELOG.md` de contratos | IMPLEMENTADO | 0.1.0/0.1.1 (Fase 1), 0.2.0 (mercados, aditivo) |

## 2. Servicios Fase 1

| Componente | Clasificación | Notas |
|---|---|---|
| `identity` — registro, verificación de email, login/refresh con rotación + detección de reuso, sesiones, logout/revocación, forgot/reset, MFA TOTP (enable/disable/verify), RBAC, rate limits, outbox | IMPLEMENTADO | Suite integration + e2e verdes |
| Envío real de email (verificación / reset) | REQUIERE PROVEEDOR | Hoy: persistido en `email_outbox` + evento; sin SMTP/provider (Fase posterior) |
| `audit` — ingesta batch append-only, RBAC por token de servicio, dedup por `event_id`, filtros + cursor, bloqueo de UPDATE/DELETE | IMPLEMENTADO | Append-only verificado por trigger/listener |
| `gateway` — proxy con validación JWT, headers de seguridad, request-id/correlation, rate limit, passthrough problem+json, `/healthz` agregado (identity+audit+market_data) y `/readyz` | IMPLEMENTADO | `/healthz` devuelve 503 si upstreams caídos (agregado, por diseño) |
| `market-data` — snapshot público `GET /api/v1/market-data/overview` (Forex/Crypto de referencia con proveedores keyless: Frankfurter→ECB, Kraken→CoinGecko; cache TTL 900/60 s, circuit breaker 3 fallos→30 s, failover, regla no-ficción `stale`/`unavailable`, cero secretos) | IMPLEMENTADO (alcance overview) | Puerto 8084; ruta pública en gateway; tests unit con `httpx.MockTransport`; smoke en contenedor con datos reales. **Pendiente (F2–F3)**: ticks/velas/WS, symbol master, histórico, `get_quote`/`get_tickers` (K §0) |
| Devices/sesiones persistentes multi-dispositivo avanzado | PENDIENTE | Tablas de sesión existentes; fingerprint de dispositivo no implementado |

## 3. Datos e infraestructura

| Componente | Clasificación | Notas |
|---|---|---|
| Compose local: PostgreSQL 17 (puerto **5433**), Redis 7, initdb con `platform_identity`/`platform_audit`/`platform_gateway` | IMPLEMENTADO | Healthy; todos los puertos de datos/obs enlazan a `127.0.0.1` (evita `localhost`→`::1`, que en Windows+Docker tarda ~2 s por conexión); psycopg exige SelectorEventLoop (mitigado en kernel + `loop_factory`) |
| Migraciones Alembic por servicio (schema propio, upgrade/downgrade) | IMPLEMENTADO | Commit explícito en `env.py` (evita autobegin); fix `path_separator` |
| Redpanda (perfil `events`) + pipeline outbox | IMPLEMENTADO | Relay en `identity/outbox.py` (reintentos con backoff exp+jitter, DLQ `dlq.<topic>`, métricas de backlog/publicados/DLQ, migración `0002_outbox_relay`) → consumidor `audit/consumer.py` (grupo `audit-service`, commit tras insert, dedup `event_id`) |
| Dockerfiles multi-stage non-root (gateway/identity/audit/market-data) | IMPLEMENTADO | Imágenes construidas; smoke `/healthz` 200 con migraciones en imagen; `market-data` smoke en contenedor con overview real |
| Imágenes publicadas en registry | PENDIENTE | Referenciadas en K8s como `platform/<svc>:dev` |
| **Despliegue en servidor OMV (Docker, `192.168.1.200`, puertos 40000-40100)** | IMPLEMENTADO | `deploy/compose.yml` (+`.env.example`, `prometheus.yml`, README): web 40000, gateway 40001, identity 40002, audit 40003, market-data 40004, datos 40010-40012 (solo `127.0.0.1`), obs 40020-40024; 14 servicios definidos (core 8 + obs 6); migraciones al arrancar (`sh -c` con comando explícito); secretos generados en servidor en `deploy/.env` (no versionado); E2E verificado 2026-09-28 (registro→login→panel, outbox→Redpanda→`audit.records`, Grafana 200); redespliegue con `market-data` **pendiente de push/confirmación** |
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
| Portada hero con acceso embebido (`AuthPanel`: pestañas Iniciar sesión/Crear cuenta reutilizando los formularios existentes; con sesión activa muestra saludo + enlace a `/panel`) + secciones: **Mercados con datos reales de referencia** (Forex EUR→USD/GBP/JPY vía BCE y Crypto BTC/ETH/USDT vía Kraken, con `source`+`ts`+badge `stale`/`dato no disponible`; commodities/índices/acciones/ETFs con badge "Próximamente · Fase 3-4"), Disponible hoy, Qué podrás hacer, Cómo empezar y aviso legal | IMPLEMENTADO | Copys i18n `es`/`en`; capacidad no implementada con badge "Próximamente · Fase"; sin cifras ni precios inventados (regla no-ficción: último bueno `stale` o `unavailable`); fetch `GET /api/v1/market-data/overview` con timeout 12 s y degradación a badges "Próximamente" si falla; E2E navegador local OK (2026-09-28): Forex/Crypto con datos reales y 0 errores de consola |
| Sistema de diseño (primitivas `src/components/ui/`: Button/Input/Field/Select/Checkbox/Card/Container/Badge/Spinner, tokens AA en `globals.css`, header responsive con menú móvil y `aria-current`) | IMPLEMENTADO | Contraste AA verificado (primario `brand-700` 5,9:1, foco `brand-800` 7,1:1) |
| BFF de autenticación (`src/app/api/auth/{login,register,session,logout}` → gateway; cookies httpOnly `at` 15 min + `rt` 30 d path `/api/auth`, `SameSite=Lax`, `Secure` por `COOKIE_SECURE`) | IMPLEMENTADO | E2E verificado contra el despliegue OMV: registro 201 → login 200 → `/panel` con `/me` real |
| Login/registro/panel de usuario (formularios con validación por campo `aria-invalid`, errores en español, contraseña ≥12 alineada al contrato, panel con datos reales de `/me`, logout) | IMPLEMENTADO | Sin datos de mercado inventados: bloques marcados "Próximamente"; MFA → aviso 409 (UI MFA `PENDIENTE`) |
| Páginas de error/404/loading propias + cabeceras de seguridad + `output: standalone` | IMPLEMENTADO | CSP con `'unsafe-inline'` (nonces `PENDIENTE`); aviso COOP ignorado sobre HTTP LAN es cosmético |
| Imagen Docker del web (`apps/web/Dockerfile`, node:22-alpine, non-root, healthcheck) | IMPLEMENTADO | Construida localmente y en el servidor OMV |
| Trading UI, catálogo de símbolos, depósitos | PENDIENTE | Fases 3–6 |
| `apps/admin-shell` (backoffice) | PENDIENTE | Fase 7 |
| Service Worker / offline completo | PENDIENTE | Manifest listo; SW con PWA completa |
| Selector de idioma (catálogo `en` existe pero inalcanzable en runtime) | PENDIENTE | Locale fijo `es`; i18n completo en fase posterior |

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
| Market data adapters + streaming WS (Fase 3) | PARCIAL | **Adelantado 2026-09-28**: snapshot `overview` con adapters reales keyless (Frankfurter/ECB, Kraken/CoinGecko), cache, breaker y failover; **sigue pendiente** ticks/velas/WS, symbol master, histórico y feeds con redistribución (X-07) |
| Trading OMS/EMS, posiciones, margin, risk (Fase 4) | PENDIENTE |
| Pagos (depósitos/retiros) | REQUIERE PROVEEDOR (adapters de pago) |
| KYC/AML | REQUIERE PROVEEDOR (proveedor de verificación) + REQUIERE DECISIÓN (alcance jurisdiccional) |
| Operar en vivo (live trading, capital real) | REQUIERE LICENCIA/REGULACIÓN — `FLAG_LIVE_TRADING=false` forzado por código (ADR-0012) |
| Identidad de marca/dominio (nombre/marca `MonedasAR` DECIDIDO 2026-09-28; `[DOMAIN]` pendiente) | REQUIERE DECISIÓN (solo dominio: Producto/Legal) |
| Locales restantes más allá de `es`/`en` (ADR-0015, 7 idiomas) | REQUIERE DECISIÓN (conjunto definitivo) |

---

## Deudas técnicas conocidas (Fase 1)

1. Rate limits se prueban a nivel unitario (fixtures relajan límites para la suite).
2. `clean_dbs` dropea schemas de la base local entre sesiones de prueba (por diseño en dev).
3. e2e usa puertos fijos 18080/18081/18083/18084 con espera de liberación; en paralelismo futuro
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
