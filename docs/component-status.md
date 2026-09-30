# Estado de componentes — clasificación

Fecha de verificación: 2026-09-30 · Fase 0 + Fase 1 (foundation) + F2.1 (ledger) + F2.2 (accounts)
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
`MarketClassCard`) y **0 errores de consola / 0 peticiones fallidas**; captura
PNG local `mercados.png` (temp, fuera del repo, no versionada). Commit `3770cc2` (53 archivos) → push `master` → CI en
GitHub **6/6 jobs `success`** (lint/tipos/gates, pruebas unit+integration+e2e,
frontend, Terraform/K8s/compose, secret-scan/vulnerabilidades, imágenes+SBOM+CVE);
gitleaks en CI sin hallazgos. Redespliegue OMV (2026-09-28): 53 archivos
transferidos a `/opt/platform` (sin git en el servidor), `compose build` de
`web`+`gateway`+`market-data` → OK y `up -d` → **14 contenedores** (core 8 +
obs 6) con los 3 reconstruidos `healthy`; `curl 127.0.0.1:40001/healthz` →
`{"status":"ok","checks":{…,"market_data":"ok"}}`, overview en `:40004` → 200 y
portada `http://192.168.1.200:40000` → 200. E2E navegador contra la portada
pública OMV: Forex/Crypto con datos reales (Kraken 16:31 UTC), Fuente sin
duplicados, 5 cards "Próximamente"; solo avisos preexistentes (COOP sobre HTTP
LAN y un prefetch RSC abortado), sin errores propios.

Evidencia F2.1 — servicio `ledger` (2026-09-29): servicio nuevo `services/ledger`
(Fase 2, BUILD-017/018/021) con API interna `POST /internal/v1/postings` (201,
`Idempotency-Key` obligatoria UUID, replay idempotente y 409 con cuerpo distinto,
ADR-0010) y `GET /internal/v1/postings/{id}`; escritura ACID de cuentas/asientos/
outbox en una transacción (`store.py`), validación de reglas de asiento pura
(`postings.py`, 79 tests unit), invariante de saldo `ledger.ledger_assert_balanced`
antes del commit, triggers append-only en transacciones/asientos (ADR-0011 §1/§2),
evento `LedgerPosted` en outbox (`PHASE2_TOPICS`, contrato 0.3.0 con test propio),
BD `platform_ledger` en initdb/CI y `uv run ledger` en 8085; fix de orden de INSERT
(transacciones antes que asientos) vía `relationship()` en `LedgerEntry`, fix de
replay idempotente (psycopg3 devuelve `rowcount=-1` en `INSERT … ON CONFLICT` sin
`RETURNING` → detección por fila devuelta) y `OUTBOX_RELAY_ENABLED` movido de volcado
global a fixture (el volcado global rompía la publicación de identity en e2e);
gateway `/healthz` agrega `ledger` (4 checks) con e2e que levanta 5 servidores
(puerto 18085); `deploy/compose.yml` con servicio `ledger` en `40005:8085`,
`docker compose config` OK; CI con `platform_ledger` y `ledger` en build/SBOM/trivy;
manifest k8s `ledger.yaml` (+ `LEDGER_URL`/`LEDGER_DATABASE_URL`) con
`kubectl kustomize` OK; docs (README, deploy/README con nota de creación manual de
`platform_ledger` en volúmenes ya inicializados, .env.example). Gates locales verdes:
`ruff check`/`format` (166 archivos), `mypy packages services` (79 archivos),
`check_boundaries`, `export_openapi --check` (5 specs) y `uv run pytest` →
**180 passed (133 unit, 44 integration, 3 e2e)** contra PostgreSQL y Redpanda reales;
`docker build -f services/ledger/Dockerfile` → imagen OK. Cierre (2026-09-30):
commit `2514840` → push `master` → CI GitHub **6/6 jobs `success`** → redespliegue
OMV verificado (15 contenedores `healthy`, `40001/healthz` con 4 checks, `40005/healthz`
ledger ok), working tree limpio.

Evidencia F2.2 — servicio `accounts` (2026-09-30): servicio nuevo `services/accounts`
(Fase 2, BUILD-017/020/023, Q-api-map §2.4) con API pública `GET/POST /api/v1/accounts`
(cursor opaco §1.4, `Idempotency-Key` UUID obligatoria §1.8 con replay y 409 con cuerpo
distinto, header `Location`+`Idempotent-Replay`), `GET/PATCH /api/v1/accounts/{id}`
(BOLA §1.7.3: recurso ajeno e inexistente → 404 idéntico; PATCH ajusta alias) y API
interna `GET /internal/v1/accounts/{id}` con JWT de servicio (§3); gating tipado:
`live` → 403 `live-not-enabled` (BUILD-020, KYC+flag en F6), matriz `jurisdictions`
vacía por defecto con fila `blocked` → 403 `jurisdiction-blocked` (BUILD-023), una
sola demo por usuario vía índice único parcial (409); auto-provisión desde
`identity.user.registered` (consumidor `accounts-service`, handler idempotente por
índice, payload inválido → commit+log+skip) con jurisdicción del propio evento;
endpoint interno de identity `GET /internal/v1/users/{id}` (perfil mínimo sin email,
`require_service`) usado como seam por `resolve_jurisdiction` (cliente HTTP
inyectable `app.state.identity_client` para tests); contratos 0.4.0 con
`AccountCreated`/`DemoAccountCreated` (`EVENT_TYPES_PHASE2`, `PHASE2_TOPICS` ×3) y
`TradingAccount`; audit consume `PHASE1_TOPICS + PHASE2_TOPICS`; gateway con
`accounts_url`, ruta `/api/v1/accounts` y `/healthz` con **5 checks**; BD
`platform_accounts` (schema `accounts`: `trading_accounts`/`jurisdictions`/
`outbox_events`) en initdb/CI/compose/k8s (`accounts.yaml`, `ACCOUNTS_URL`/
`ACCOUNTS_DATABASE_URL`), `deploy/compose.yml` con servicio `accounts` en
`40006:8086`; deudas documentadas: step-up MFA inexistente en F1 (cierre de cuenta
`POST …/close` diferido a F2.3), recarga de demo sin endpoint, sin `profiles`/
`account_limits` (F4), `leverage` nullable null (BUILD-037), backfill del consumidor
con `auto_offset_reset=earliest` (usuarios históricos reciben demo al arrancar).
Tests nuevos: 12 integration (`test_accounts`) + 3 internal en identity +
e2e de auto-provisión vía gateway. Gates locales verdes: `ruff check`/`format`
(121 archivos), `mypy packages services` (93 archivos), `check_boundaries`,
`export_openapi --check` (6 specs) y `uv run pytest` → **197 passed (134 unit,
59 integration, 4 e2e)** contra PostgreSQL y Redpanda reales. **Pendiente**:
commit/push (CI GitHub) y redespliegue OMV con creación previa de
`platform_accounts`.

---

## 1. Núcleo y contratos

| Componente | Clasificación | Notas |
|---|---|---|
| `packages/platform-kernel` (config, errores RFC 9457, logging JSON, auth JWT+roles, tokens, `money` Decimal, rate limit, idempotencia, middleware request-id, métricas Prometheus, loop_factory Windows) | IMPLEMENTADO | mypy strict; tests unitarios; redacción de secretos en logs |
| Exportación **traces OpenTelemetry** desde servicios | IMPLEMENTADO | SDK en `platform_kernel/telemetry.py` (OTLP/HTTP, instrumentación FastAPI+httpx, propagación W3C `traceparent`); activo solo con `OTEL_ENDPOINT`; E2E verificado contra Tempo (REQ-057) |
| `packages/platform-contracts` (roles, envelope de eventos, headers internos, esquemas de audit, contrato de mercados `market_data.py`) | IMPLEMENTADO | 9 eventos del catálogo Fase 1 + `LedgerPosted`/`AccountCreated`/`DemoAccountCreated` (Fase 2, `EVENT_TYPES_PHASE2`/`PHASE2_TOPICS`); `MarketOverview`/`OverviewQuote` con `simulated: false` estructural (G3/X-07 bloqueado) |
| OpenAPI por servicio (`platform-contracts/openapi/*.yaml`) + tests de contrato | PARCIAL | 6 specs canónicos exportados (`tools/export_openapi.py`, gate `--check` en CI, `test_openapi_sync`); falta test productor/consumidor en runtime |
| `platform-contracts/CHANGELOG.md` de contratos | IMPLEMENTADO | 0.1.0/0.1.1 (Fase 1), 0.2.0 (mercados, aditivo), 0.3.0 (ledger, aditivo), 0.4.0 (cuentas, aditivo) |

## 2. Servicios Fase 1

| Componente | Clasificación | Notas |
|---|---|---|
| `identity` — registro, verificación de email, login/refresh con rotación + detección de reuso, sesiones, logout/revocación, forgot/reset, MFA TOTP (enable/disable/verify), RBAC, rate limits, outbox | IMPLEMENTADO | Suite integration + e2e verdes |
| Envío real de email (verificación / reset) | REQUIERE PROVEEDOR | Hoy: persistido en `email_outbox` + evento; sin SMTP/provider (Fase posterior) |
| `audit` — ingesta batch append-only, RBAC por token de servicio, dedup por `event_id`, filtros + cursor, bloqueo de UPDATE/DELETE | IMPLEMENTADO | Append-only verificado por trigger/listener |
| `gateway` — proxy con validación JWT, headers de seguridad, request-id/correlation, rate limit, passthrough problem+json, `/healthz` agregado (identity+audit+market_data+ledger+accounts) y `/readyz` | IMPLEMENTADO | `/healthz` devuelve 503 si upstreams caídos (agregado, por diseño) |
| `market-data` — snapshot público `GET /api/v1/market-data/overview` (Forex/Crypto de referencia con proveedores keyless: Frankfurter→ECB, Kraken→CoinGecko; cache TTL 900/60 s, circuit breaker 3 fallos→30 s, failover, regla no-ficción `stale`/`unavailable`, cero secretos) | IMPLEMENTADO (alcance overview) | Puerto 8084; ruta pública en gateway; tests unit con `httpx.MockTransport`; smoke en contenedor con datos reales. **Pendiente (F2–F3)**: ticks/velas/WS, symbol master, histórico, `get_quote`/`get_tickers` (K §0) |
| Devices/sesiones persistentes multi-dispositivo avanzado | PENDIENTE | Tablas de sesión existentes; fingerprint de dispositivo no implementado |

## 2b. Servicios Fase 2

| Componente | Clasificación | Notas |
|---|---|---|
| `ledger` — asientos double-entry append-only: `POST /internal/v1/postings` (201, `Idempotency-Key` UUID obligatoria, replay idempotente, 409 con cuerpo distinto, ADR-0010), `GET /internal/v1/postings/{id}`, `/healthz` y `/readyz`; cuentas auto-creadas, invariante de saldo `ledger_assert_balanced` antes del commit, triggers append-only (ADR-0011), outbox `LedgerPosted`→Redpanda, relay propio | IMPLEMENTADO (alcance F2.1) | Puerto 8085, BD `platform_ledger` (migración única `0001_initial`), API interna (sin ruta pública en gateway por ahora; Q-api-map §2.6 statements/extractos sigue pendiente). Suite: 79 unit (`test_ledger_postings`) + 22 integration (`test_ledger`) + e2e (health agregado) verdes |
| `accounts` — cuentas de trading: `GET/POST /api/v1/accounts` (cursor opaco §1.4, `Idempotency-Key` UUID obligatoria §1.8 con replay/409, `Location`+`Idempotent-Replay`), `GET/PATCH /api/v1/accounts/{id}` (alias; BOLA §1.7.3 404 idéntico), `GET /internal/v1/accounts/{id}` (JWT de servicio, §3); gating: `live`→403 `live-not-enabled` (BUILD-020), matriz `jurisdictions` `blocked`→403 tipado (BUILD-023), una demo por usuario (índice único parcial→409); auto-provisión desde `identity.user.registered` (consumidor idempotente); outbox `AccountCreated`+`DemoAccountCreated` | IMPLEMENTADO (alcance F2.2) | Puerto 8086, BD `platform_accounts` (schema `accounts`: `trading_accounts`/`jurisdictions`/`outbox_events`, migración `0001_initial`), ruta pública en gateway `/api/v1/accounts`; `resolve_jurisdiction` consulta el endpoint interno de identity (seam `app.state.identity_client` para tests). Sin step-up MFA (F1 no lo tiene; cierre de cuenta diferido a F2.3), sin recarga de demo, sin `profiles`/`account_limits` (F4). Suite: 12 integration (`test_accounts`) + 3 internal en identity + e2e auto-provisión verdes |

## 3. Datos e infraestructura

| Componente | Clasificación | Notas |
|---|---|---|
| Compose local: PostgreSQL 17 (puerto **5433**), Redis 7, initdb con `platform_identity`/`platform_audit`/`platform_gateway`/`platform_ledger`/`platform_accounts` | IMPLEMENTADO | Healthy; todos los puertos de datos/obs enlazan a `127.0.0.1` (evita `localhost`→`::1`, que en Windows+Docker tarda ~2 s por conexión); psycopg exige SelectorEventLoop (mitigado en kernel + `loop_factory`); en volúmenes previos a F2.2 crear `platform_accounts` a mano (initdb no re-ejecuta) |
| Migraciones Alembic por servicio (schema propio, upgrade/downgrade) | IMPLEMENTADO | Commit explícito en `env.py` (evita autobegin); fix `path_separator` |
| Redpanda (perfil `events`) + pipeline outbox | IMPLEMENTADO | Relay en `identity/outbox.py` (reintentos con backoff exp+jitter, DLQ `dlq.<topic>`, métricas de backlog/publicados/DLQ, migración `0002_outbox_relay`) → consumidor `audit/consumer.py` (grupo `audit-service`, commit tras insert, dedup `event_id`) |
| Dockerfiles multi-stage non-root (gateway/identity/audit/market-data/ledger/accounts) | IMPLEMENTADO | Imágenes construidas; smoke `/healthz` 200 con migraciones en imagen; `market-data` smoke en contenedor con overview real; `ledger` build OK (2026-09-29); `accounts` build OK (2026-09-30) |
| Imágenes publicadas en registry | PENDIENTE | Referenciadas en K8s como `platform/<svc>:dev` |
| **Despliegue en servidor OMV (Docker, `192.168.1.200`, puertos 40000-40100)** | IMPLEMENTADO | `deploy/compose.yml` (+`.env.example`, `prometheus.yml`, README): web 40000, gateway 40001, identity 40002, audit 40003, market-data 40004, ledger 40005, accounts 40006, datos 40010-40012 (solo `127.0.0.1`), obs 40020-40024; 16 servicios definidos (core 10 + obs 6); migraciones al arrancar (`sh -c` con comando explícito); secretos generados en servidor en `deploy/.env` (no versionado); E2E verificado 2026-09-28 (registro→login→panel, outbox→Redpanda→`audit.records`, Grafana 200); redespliegue `market-data` verificado 2026-09-28 (commit `3770cc2`, 14 contenedores, `/healthz` con `market_data: ok`); redespliegue F2.1 verificado 2026-09-30 (commit `2514840`, 15 contenedores `healthy`, `/healthz` con 4 checks, `40005/healthz` ledger ok; `CREATE DATABASE platform_ledger` manual). **Pendiente (2026-09-30)**: redespliegue F2.2 con `accounts` + `CREATE DATABASE platform_accounts` manual (el volumen `pgdata` no re-ejecuta initdb) |
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
| Atributos/propagación OTel traces extremo a extremo | IMPLEMENTADO | `init_telemetry` + `instrument_app` en los 6 servicios + `traceparent` de salida; E2E verificado: batch de spans del servicio llega al collector y Tempo responde en `/api/search` (ADR-0013, REQ-057) |

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
| `.github/workflows/ci.yml` | IMPLEMENTADO | 6 jobs: `quality` (ruff/format/mypy/fronteras/OpenAPI), `test` (pytest con PostgreSQL+Redpanda efímeros, 5 bases incl. `platform_accounts`), `web` (lint/typecheck/build), `security` (gitleaks+pip-audit+npm audit), `supply-chain` (docker build+SBOM syft+trivy CRITICAL, 6 imágenes incl. `accounts`), `infra` (terraform/kustomize/compose); actions pinnadas por SHA; CI 6/6 verde en GitHub (último cierre de F2.1: commit `2514840`) |
| dependabot + secret-scan + análisis de dependencias + SBOM/CVE | IMPLEMENTADO | `.github/dependabot.yml` (pip/npm/actions/docker); gitleaks con `.gitleaks.toml`; pip-audit vía `uv export`; npm audit (bloqueo a nivel crítico); syft SBOM como artefacto; trivy CRITICAL bloquea |
| Path filters por servicio | PARCIAL | Solo `paths-ignore` global de `docs/**`/`**/*.md`; filtros por servicio cuando haya más teams/paths (ADR de fase posterior) |
| CODEOWNERS y branch protection | REQUIERE DECISIÓN | No hay usernames/owners conocidos en el repo; requiere cuentas de GitHub (G-security §1.7) |
| Tests de contrato productor/consumidor | PENDIENTE | OpenAPI versionado ya existe; falta ejecutar contratos en runtime bidireccional |

## 7. Dominio de negocio (roadmap por fases)

| Componente | Clasificación |
|---|---|
| Ledger double-entry, wallet, cuentas de trading (Fase 2) | PARCIAL | **F2.1 ledger IMPLEMENTADO 2026-09-29** (asientos double-entry append-only, idempotencia ADR-0010, outbox `LedgerPosted`); **F2.2 accounts IMPLEMENTADO 2026-09-30** (cuentas demo/live con gating, cursor, auto-provisión, matriz de jurisdicciones); **sigue pendiente** wallet, proyecciones de extractos (Q-api-map §2.6), cierre de cuenta y recarga de demo (F2.3) |
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
3. e2e usa puertos fijos 18080/18081/18083/18084/18085/18086 con espera de liberación; en paralelismo futuro
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
