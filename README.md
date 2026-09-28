# [PROJECT_NAME] — Plataforma FinTech/Trading de derivados OTC

Marca: `[BRAND_NAME]` · Dominio: `[DOMAIN]` · Estado: **Fase 0 (A–Z) + Fase 1 (foundation)**

Plataforma de trading de derivados OTC con paridad funcional objetivo frente a proveedores
de referencia, construida desde cero. Los placeholders `[PROJECT_NAME]`, `[DOMAIN]` y
`[BRAND_NAME]` se sustituyen cuando Producto/Legal definan la identidad.

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

# 2. Infraestructura local (PostgreSQL en puerto 5433, Redis en 6379)
docker compose -f infrastructure/compose/compose.yml up -d postgres redis

# 3. Suite de pruebas (unit + integration + e2e): requiere el paso 2
uv run pytest

# 4. Servicios (cada uno en una terminal; migraciones automáticas en entornos local/test)
uv run identity     # http://localhost:8081
uv run gateway      # http://localhost:8080  (entrypoint; requiere identity+audit arriba)
uv run audit        # http://localhost:8083

# 5. Frontend shell (Next.js 15)
npm install
npm run dev --workspace apps/web   # http://localhost:3000
```

### Comandos de calidad

```powershell
uv run ruff check .            # lint Python
uv run ruff format --check .   # formato
uv run mypy packages services  # tipos strict
npm run lint --workspace apps/web
npm run typecheck --workspace apps/web
npm run build --workspace apps/web
```

### Imágenes Docker (multi-stage, non-root)

```powershell
docker build -f services/identity/Dockerfile -t platform/identity:dev .
docker build -f services/gateway/Dockerfile  -t platform/gateway:dev .
docker build -f services/audit/Dockerfile    -t platform/audit:dev .
```

### Observabilidad (perfil `obs`)

```powershell
docker compose -f infrastructure/compose/compose.yml --profile obs up -d
# Prometheus http://localhost:9090 · Grafana http://localhost:3001 · OTLP/HTTP :4318
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
| `services/gateway` · `identity` · `audit` | Microservicios Fase 1 (uno por bounded context, schema propio) |
| `tests/` | Suite cruzada: unit, integration (PostgreSQL real), e2e (3 servidores reales) |
| `apps/web/` | Frontend shell Next.js 15 (npm workspaces, TS estricto, Tailwind 4, PWA) |
| `infrastructure/compose/` | Stack local (postgres:5433, redis, redpanda, perfiles `events`/`obs`) |
| `infrastructure/monitoring/` | Config de OTel Collector y Prometheus |
| `infrastructure/kubernetes/` | Manifests kustomize (base + overlay dev) — **preparados, NO aplicados** |
| `.github/workflows/ci.yml` | CI: ruff/format/mypy + suite pytest con PostgreSQL efímero |

## Contratos básicos

- Errores: RFC 9457 `application/problem+json` con `request_id`/`correlation_id`.
- Auth: JWT access ≤15 min + refresh rotativo con detección de reuso; token de servicio `typ=service` ≤5 min.
- Idempotencia: cabecera `Idempotency-Key` en mutaciones.
- Eventos: outbox transaccional → Audit Service (dedup por `event_id`).
- Dinero: `Decimal` + `ROUND_HALF_UP`; floats prohibidos (unit-tested).

## Enlaces

- Decisiones: `docs/phase0/00-decisions.md`
- Roadmap: `docs/phase0/T-roadmap.md`
- Estado por componente: `docs/component-status.md`
