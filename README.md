# MonedasAR — Plataforma FinTech/Trading de derivados OTC

Marca: `MonedasAR` · Dominio: `[DOMAIN]` · Estado: **Fase 0 (A–Z) + Fase 1 (foundation) + F2.1/F2.2 (ledger · accounts)**

Plataforma de trading de derivados OTC con paridad funcional objetivo frente a proveedores
de referencia, construida desde cero. Nombre y marca definidos (`MonedasAR`, 00-decisions §1);
el dominio permanece como marcador literal `[DOMAIN]` hasta que Legal confirme su definición.

> **Seguridad**: `FLAG_LIVE_TRADING` es `false` por diseño y una validación lo hace fallar si
> se intenta activar (ADR-0012). Las credenciales de compose/README son **solo para
> desarrollo local**. No hay secretos reales en el repositorio.

---

## Requisitos

- Docker Desktop (PostgreSQL 17 y Redis 7 en compose)
- Python 3.13 + [uv](https://docs.astral.sh/uv/)
- Node.js ≥ 22 (npm incluido)
- Opcional: `kubectl` (validación de manifests), perfil `obs` de compose (observabilidad)

## Arranque rápido

```powershell
# 1. Dependencias Python (workspace uv — TODOS los miembros)
uv sync --all-packages

# 2. Infraestructura local (PostgreSQL en 5433, Redis en 6379, Redpanda en 19092)
#    Sin Redpanda la suite pasa igual, pero los tests de eventos se saltan.
docker compose -f infrastructure/compose/compose.yml --profile events up -d postgres redis redpanda

#    Nota: initdb solo corre con el volumen pgdata vacío. Si el volumen es anterior a
#    F2.2, crear la base una sola vez:
#    docker compose -f infrastructure/compose/compose.yml exec postgres psql -U platform -d postgres -c "CREATE DATABASE platform_accounts;"

# 3. Suite de pruebas (unit + integration + e2e): requiere el paso 2
uv run pytest

# 4. Servicios (cada uno en una terminal; migraciones automáticas en entornos local/test)
uv run identity     # http://localhost:8081
uv run gateway      # http://localhost:8080  (entrypoint; requiere identity+audit arriba)
uv run audit        # http://localhost:8083
uv run market-data  # http://localhost:8084  (opcional: datos reales de la sección Mercados)
uv run ledger       # http://localhost:8085  (asientos double-entry; API interna)
uv run accounts     # http://localhost:8086  (cuentas demo/live; API pública + interna)

# 5. Frontend shell (Next.js 15)
npm install
npm run dev --workspace apps/web   # http://localhost:3000
```

### Comandos de calidad

```powershell
uv run ruff check .            # lint Python
uv run ruff format --check .   # formato
uv run mypy packages services  # tipos strict
uv run python tools/check_boundaries.py      # fronteras del monorepo
uv run python tools/export_openapi.py --check # OpenAPI sin deriva
npm run lint --workspace apps/web
npm run typecheck --workspace apps/web
npm run build --workspace apps/web
```

### Imágenes Docker (multi-stage, non-root)

```powershell
docker build -f services/identity/Dockerfile -t platform/identity:dev .
docker build -f services/gateway/Dockerfile  -t platform/gateway:dev .
docker build -f services/audit/Dockerfile    -t platform/audit:dev .
docker build -f services/market-data/Dockerfile -t platform/market-data:dev .
docker build -f services/ledger/Dockerfile   -t platform/ledger:dev .
docker build -f services/accounts/Dockerfile -t platform/accounts:dev .
```

### Observabilidad (perfil `obs`)

```powershell
docker compose -f infrastructure/compose/compose.yml --profile obs up -d
# Prometheus http://localhost:9090 · Grafana http://localhost:3001 (datasources
# prometheus/loki/tempo provisionadas + dashboard RED) · Loki :3100 · Tempo :3200
# Alloy → logs JSON de los contenedores platform-* a Loki
# Trazas: ejecutar un servicio con OTEL_ENDPOINT=http://127.0.0.1:4318 exporta a Tempo
```

> **Windows**: los endpoints locales usan `127.0.0.1` (no `localhost`) — el intento previo
> a `::1` (IPv6) ante puertos con publicación IPv4 de Docker cuesta ~2 s por conexión.

### Despliegue en servidor OMV (Docker)

Stack completo publicado en el servidor de la LAN con **todos los puertos en el
rango 40000–40100**: web `40000` · gateway `40001` · identity `40002` · audit `40003` · market-data `40004` · ledger `40005` · accounts `40006`
· datos `40010–40012` (solo `127.0.0.1` del servidor) · observabilidad `40020–40024`.

```bash
# En el servidor (ver deploy/README.md para el detalle completo):
cd /opt/platform && docker compose -f deploy/compose.yml up -d
```

---

## Estructura

| Ruta | Contenido |
|---|---|
| `docs/phase0/` | Decisiones canónicas A–Z (fuente de verdad: `00-decisions.md`) |
| `docs/adr/` | ADR-0001…ADR-0020 |
| `docs/component-status.md` | Matriz de clasificación de componentes (IMPLEMENTADO/PARCIAL/…) |
| `packages/platform-kernel/` | Núcleo Python compartido (config, errores, auth, dinero, logs, métricas) |
| `packages/platform-contracts/` | Contratos: roles, envelope de eventos, headers, esquemas de auditoría |
| `services/gateway` · `identity` · `audit` · `market-data` · `ledger` · `accounts` | Microservicios (uno por bounded context, schema propio) |
| `tests/` | Suite cruzada: unit, integration (PostgreSQL real), e2e (6 servidores reales) |
| `apps/web/` | Frontend shell Next.js 15 (npm workspaces, TS estricto, Tailwind 4, PWA) |
| `infrastructure/compose/` | Stack local (postgres:5433, redis, redpanda, perfiles `events`/`obs`) |
| `infrastructure/monitoring/` | OTel Collector, Prometheus, Loki, Tempo, Alloy y Grafana (dashboard RED) |
| `infrastructure/terraform/` | Estructura IaC inicial (REQUIERE PROVEEDOR; `terraform validate` OK) |
| `infrastructure/kubernetes/` | Manifests kustomize (base + overlay dev) — **preparados, NO aplicados** |
| `.github/workflows/ci.yml` | CI: quality · test · web · security (gitleaks/pip-audit/npm audit) · supply-chain (SBOM/trivy) · infra (terraform/kustomize/compose) |
| `.github/dependabot.yml` | Renovación semanal de pip/npm/actions/docker |
| `deploy/` | Despliegue en servidor OMV: `compose.yml` (puertos 40000-40100), `.env.example`, `prometheus.yml`, runbook |

## Contratos básicos

- Errores: RFC 9457 `application/problem+json` con `request_id`/`correlation_id`.
- Auth: JWT access ≤15 min + refresh rotativo con detección de reuso; token de servicio `typ=service` ≤5 min.
- Idempotencia: cabecera `Idempotency-Key` en mutaciones.
- Eventos: outbox transaccional → Redpanda (relay con reintentos/backoff y DLQ) → Audit
  Service (consumer con dedup por `event_id`); API HTTP de ingesta batch disponible.
- Dinero: `Decimal` + `ROUND_HALF_UP`; floats prohibidos (unit-tested).

## Enlaces

- Decisiones: `docs/phase0/00-decisions.md`
- Roadmap: `docs/phase0/T-roadmap.md`
- Estado por componente: `docs/component-status.md`
