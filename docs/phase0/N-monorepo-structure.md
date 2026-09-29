# N — Estructura del Monorepo

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `MonedasAR` · Dominio: `[DOMAIN]` · Marca: `MonedasAR`

Fuente de verdad: `00-decisions.md` §3 (catálogo de servicios y aislamiento por schema) y ADR-0001 (monorepo único con `apps/ services/ packages/ infrastructure/`). Este documento define la forma concreta del repositorio para la Fase 1 y su crecimiento por fases.

---

## 1. Por qué monorepo y no multirepo (ADR-0001)

| Argumento a favor del monorepo | Cómo aplica aquí |
|---|---|
| **Cambios atómicos** | Un cambio de contrato (`platform-contracts`) + su productor + su consumidor + su cliente se mergean en **un solo PR**; imposible quedar desincronizado entre repos. |
| **Contratos y clientes siempre al día** | OpenAPI/eventos viven en el mismo repo: el `api-client` y los tests de contrato se generan y validan en el mismo CI que el servicio. |
| **Fronteras verificables** | Un solo pipeline aplica ruff/ESLint con reglas de dominio: violar el aislamiento entre servicios **falla el CI** (REQ-077, BUILD-001). |
| **Consistencia de tooling** | Una versión de Python/Node/TS/linters para todo; sin deriva de configuración entre 13+ repos. |
| **Reutilización sin versionado frágil** | `packages/` se consumen por workspace local: sin publicar en registry ni sincronizar tags entre repos. |
| **Onboarding y descubrimiento** | Un `docs/` canónico, un ADR set, un árbol para entender el sistema entero. |
| **Coste operativo** | 1 repo, 1 conjunto de secretos de CI, 1 configuración de branch protection. |

| Contra (y mitigación) | Mitigación |
|---|---|
| CI crece con el tamaño del repo | **Path filters**: cada workflow corre solo sobre rutas afectadas; caché de dependencias por lockfile. |
| Mayor blast radius de un merge defectuoso | Tests por servicio + gates de contrato + `CODEOWNERS` por directorio. |
| Dificultad de permisos finos por equipo | `CODEOWNERS` por `services/<nombre>/`; reglas de rama obligatorias por path. |
| Checkout más pesado | Sparse/checkout selectivo en jobs; artefactos por servicio. |

**Multirepo se descarta** en Fase 1 por: sincronización manual de contratos, matriz de versiones entre 13 servicios + frontend, y ausencia todavía de equipos independientes (criterio de extracción de ADR-0002 que todavía no se cumple). Se reconsidera **solo** si aparece un equipo/proceso realmente independiente o el CI deja de escalar tras medirlo.

---

## 2. Árbol completo (propuesto, Fase 1 y crecimiento por fases)

```text
platform/
├── README.md                     # arranque rápido: compose up, tests, comandos
├── AGENTS.md                     # reglas para agentes/asistentes (si aplica)
├── .gitignore                    # ignora .env, __pycache__, node_modules, .next, dist
├── .editorconfig                 # indentación/UTF-8 finos por tipo de archivo
├── .env.example                  # placeholders de variables (NUNCA valores reales)
├── uv.lock                       # lock único del workspace Python (uv)
├── pyproject.toml                # raíz del workspace uv: members + tool config compartido
├── pnpm-workspace.yaml           # raíz del workspace TS: apps/*, packages/*
├── package.json                  # scripts raíz (lint, typecheck, test, e2e)
├── tsconfig.base.json            # TS estricto base heredado por todos los paquetes TS
├── Makefile / justfile           # atajos: up, test, lint, migrate (un solo entrypoint)
│
├── apps/                         # aplicaciones desplegables (frontend)
│   ├── web/                      # MonedasAR web: Next.js 15 App Router + PWA (público)
│   │   ├── src/app/              # rutas (App Router), layouts, i18n/RTL
│   │   ├── src/features/         # feature modules de UI (no lógica de negocio server)
│   │   ├── src/instrumentation.ts# inicialización OTel del lado servidor
│   │   ├── public/               # manifest PWA, iconos propios, offline shell
│   │   └── tests/                # tests unitarios de componentes
│   └── admin-shell/              # backoffice shell (Fase 7; esqueleto preparado en Fase 1)
│
├── services/                     # microservicios backend (uno por bounded context)
│   ├── gateway/                  # F1: edge — routing, JWT, rate limit, headers, request-id
│   ├── identity/                 # F1: usuarios, credenciales, sesiones, MFA, RBAC, devices
│   ├── audit/                    # F1: log append-only de acciones críticas (consumidor)
│   ├── accounts/                 # F2: cuentas de trading, perfiles, jurisdicción
│   ├── wallet/                   # F2: balances multi-moneda (proyección, no fuente de verdad)
│   ├── ledger/                   # F2: double-entry append-only, fuente de verdad financiera
│   ├── market-data/              # F1+ (2026-09-28): snapshot overview keyless; F3: ticks, streaming WS, histórico
│   ├── trading/                  # F4: OMS, EMS, posiciones, margin, PnL
│   ├── risk/                     # F4: límites, circuit breakers, kill switches
│   ├── payments/                 # F6: depósitos/retiros vía adapters
│   ├── kyc/                      # F6: orquestación KYC/AML con adapters de proveedor
│   ├── notification/             # F2+: email/SMS/push/in-app/webhook (adapters)
│   └── admin/                    # F7: backoffice BFF
│       # Cada servicio tiene EXACTAMENTE esta forma (ejemplo con identity):
│       #
│       # services/identity/
│       # ├── pyproject.toml        # paquete miembro del workspace uv + deps propias
│       # ├── Dockerfile            # multi-stage, non-root, imagen platform/identity
│       # ├── alembic.ini           # cadenas de migración PROPIAS de este servicio
│       # ├── migrations/           # revisiones Alembic de ESTE servicio (ver §8)
│       # ├── src/identity/
│       # │   ├── main.py           # entrypoint ASGI + wiring de lifespan
│       # │   ├── api/              # routers FastAPI + schemas Pydantic de entrada/salida
│       # │   ├── domain/           # entidades, reglas de negocio, invariantes (sin framework)
│       # │   ├── application/      # casos de uso, orquestación, transacciones, outbox
│       # │   ├── infrastructure/   # repositorios SQLAlchemy, clientes Redis/Redpanda, adapters
│       # │   ├── events/           # productores (outbox) y consumidores propios
│       # │   └── config.py         # settings desde env (sin secretos literales)
│       # ├── tests/                # unitarios + integración (testcontainers) del servicio
│       # └── openapi.yaml          # contrato exportado (generado, validado en CI)
│
├── packages/                     # código compartido SIN despliegue propio
│   ├── platform-kernel/          # Python: núcleo técnico compartido (infraestructura pura)
│   │   └── src/platform_kernel/  # config, logging+OTel, errores base, outbox, idempotency,
│   │                             # pagination cursor, time UTC, money helpers (Decimal)
│   ├── platform-contracts/       # FUENTE DE VERDAD de contratos (ver §7)
│   │   ├── openapi/<servicio>.yaml   # OpenAPI por servicio
│   │   ├── events/<Event>.json       # payload por event_type + schema_version
│   │   └── CHANGELOG.md              # todo cambio de contrato, con clasificación
│   ├── ui/                       # design system propio: tokens, componentes React, iconos
│   ├── api-client/               # cliente TS generado desde platform-contracts
│   ├── types/                    # tipos TS generados (eventos y DTOs)
│   ├── config/                   # presets compartidos: eslint, tsconfig, tailwind, prettier
│   └── security/                 # TS: manejo de token en cliente, nonce/CSP, sanitización
│
├── infrastructure/
│   ├── compose/                  # docker-compose local: postgres17, redis7, redpanda, minio,
│   │                             # otel-collector, grafana/prometheus/loki/tempo + healthchecks
│   ├── kubernetes/
│   │   ├── base/                 # deployments/services/configmaps por servicio (kustomize)
│   │   └── overlays/             # dev/staging/prod con valores PLACEHOLDER (no aplicados en F1)
│   ├── terraform/                # SOLO estructura: módulos, variables, outputs; sin estado
│   │                             # ni credenciales; `terraform validate` en CI
│   └── monitoring/               # dashboards Grafana, reglas Prometheus, config OTel
│
├── docs/
│   ├── phase0/                   # A–Z: decisiones canónicas, stack (M), monorepo (N), etc.
│   ├── adr/                      # ADR-0001… (plantilla en docs/templates/)
│   ├── runbooks/                 # operación: alertas, restore, rotation, incidentes
│   ├── api/                      # guías de uso de API/WS y política de deprecación
│   └── templates/                # plantillas: ADR, feature spec, DoD
│
├── scripts/                      # automatización de repo (bash/pwsh/python): scaffolding de
│   │                             # servicio, generación de clientes, chequeos de frontera
├── tests/                        # tests que cruzan servicios (no viven en un servicio)
│   ├── contract/                 # valida OpenAPI/eventos vs implementación (productor y consumidor)
│   ├── e2e/                      # Playwright: flujos DEMO completos contra compose
│   ├── invariantes/              # propiedades financieras con hypothesis (BUILD-024)
│   └── load/                     # k6 (locust a evaluar): escenarios y umbrales p95
│
├── .github/
│   ├── workflows/                # ci.yml, ci-<servicio>.yml (path filters), nightly.yml,
│   │                             # release/e2e, secret-scan, sbom
│   ├── CODEOWNERS                # owner por directorio (services/*, packages/*, infra/*)
│   └── dependabot.yml            # renovación programada de deps y actions (§11 de M)
│
└── .opencode/                    # herramientas/configuración de agentes del proyecto (si aplica)
```

> Los directorios marcados con fase (F2…F7) **no se crean vacíos en Fase 1**: `services/` solo contiene `gateway`, `identity`, `audit` + los scaffolds estrictamente necesarios para que el layout y los lints de frontera existan (BUILD-001). El árbol anterior muestra el estado objetivo de referencia.

---

## 3. Detalle por directorio: propósito, dueño y reglas

| Directorio | Propósito | Dueño | Qué va aquí | Qué NO va aquí |
|---|---|---|---|---|
| `apps/web` | Aplicación pública Next.js 15 + PWA | Platform/Web | Rutas, UI, i18n, consumo de `api-client`, estados de carga/error | Reglas de negocio server, acceso directo a DB/Redis, secretos |
| `apps/admin-shell` | Shell del backoffice (BFF `admin` como API) | Platform/Admin | Layout/permisos de UI admin | Lógica de dominio; llamadas que no sean al BFF `admin` |
| `services/<nombre>` | Un bounded context, desplegable e independiente | ver tabla de dueños en `O-database-strategy.md` §2 | Dominio, API propia, eventos, migraciones, tests, Dockerfile | Código de otro servicio, tablas de otro schema, UI, infraestructura de plataforma |
| `packages/platform-kernel` | Núcleo técnico Python compartido | Platform/Infra | Config, errores base, logging/OTel, outbox, idempotency, tiempo UTC, dinero (`Decimal`) | Reglas de negocio, modelos de entidades de un servicio, clientes HTTP de otros servicios |
| `packages/platform-contracts` | Contratos fuente de verdad (OpenAPI + eventos) | Platform/API (revisión del owner del servicio productor) | Specs versionados, CHANGELOG de contratos | Implementación, lógica, generación de código ejecutada a mano |
| `packages/ui` | Design system propio | Platform/Web | Tokens, componentes React, iconografía propia | Lógica de negocio, fetch a APIs, dependencias pesadas de runtime |
| `packages/api-client`, `packages/types` | Consumidores **generados** de contratos | Platform/API | Código generado (no editado a mano) | Ediciones manuales; reglas de negocio |
| `packages/config` | Presets de lint/formato/TS/Tailwind | Platform/Infra | Configuración compartida | Reglas de negocio; overrides por servicio disfrazados |
| `packages/security` | Utilidades de seguridad **en cliente** | Platform/Security | Manejo de token, CSP/nonce, sanitización | Manejo de secretos, hashing de passwords (eso es de `identity`) |
| `infrastructure/compose` | Stack local reproducible | Platform/Infra | Compose con healthchecks | Configuración de producción |
| `infrastructure/kubernetes` | Manifests preparados (kustomize) | Platform/Infra | base + overlays con placeholders | Credenciales, valores reales de producción, Helm charts |
| `infrastructure/terraform` | Estructura de IaC | Platform/Infra | Módulos/variables/outputs válidos | Estado, proveedores con credenciales, recursos aplicados |
| `infrastructure/monitoring` | Dashboards/reglas/collector config | Platform/Observability | Dashboards RED/SLO, alertas con runbook asociado | Logs de aplicaciones, datos de negocio |
| `docs/phase0` | Decisiones canónicas de diseño | Arquitectura | Documentos A–Z consistentes con `00-decisions.md` | Manuales de usuario finales, especificaciones de código |
| `docs/adr` | Decisiones arquitectónicas registradas | Arquitectura | ADRs con contexto/decisión/consecuencias | Documentos operativos |
| `docs/runbooks` | Operación bajo alerta/incidente | Platform/Observability + owner del servicio | Procedimientos verificables | Especificaciones de feature |
| `docs/api` | Guías y política de API/WS | Platform/API | Uso, autenticación, deprecación, versionado | El contrato en sí (eso es `platform-contracts`) |
| `scripts` | Automatización de repo | Platform/Infra | Scaffolding, generadores, chequeos | Lógica de negocio; despliegues a producción |
| `tests/contract` | Compatibility de contratos | Platform/API | Tests productor/consumidor | Tests unitarios de un servicio |
| `tests/e2e` | Flujos completos DEMO | Platform/QA | Playwright contra compose | Pruebas de integración de un solo servicio |
| `tests/invariantes` | Propiedades financieras globales | Trading/Ledger + QA | hypothesis sobre ledger/wallet/idempotency | Casos de UI |
| `tests/load` | Rendimiento y SLO | Platform/Infra + owner del servicio | k6 con umbrales p95 | Pruebas funcionales |
| `.github/workflows` | CI/CD | Platform/Infra | Pipelines con path filters y gates | Secretos en claro; pasos manuales no auditables |

---

## 4. Workspaces

### 4.1 Python — `uv`

- Raíz: `pyproject.toml` con `[tool.uv.workspace] members = ["services/*", "packages/platform-kernel"]` y un **único `uv.lock`** en la raíz (reproducibilidad total).
- Cada servicio es un paquete instalable (`src/<servicio>/`) con sus **propias dependencias**: un servicio no hereda dependencias de otro salvo `platform-kernel` (declarándolo explícitamente).
- Comandos raíz: `uv sync` (todo), `uv run --package identity pytest` (por servicio), `uv run ruff check .`, `uv run mypy .`.
- Imágenes Docker: `uv sync --frozen --no-dev` en etapa de build → artefacto final solo con el paquete del servicio + lock.
- Regla: **nunca** editar `uv.lock` manualmente; cambios solo por `uv add/remove --package <svc>` dentro de PR.

### 4.2 TypeScript — `pnpm` workspaces

- Raíz: `pnpm-workspace.yaml` con `apps/*`, `packages/*`; **único `pnpm-lock.yaml`**; Node LTS fijado (`.nvmrc`/`engines`) y pnpm vía corepack (sin instalación global adicional).
- Alias internos: `@platform/ui`, `@platform/api-client`, `@platform/types`, `@platform/config`, `@platform/security` resuelven por workspace (sin publicar en registry).
- Comandos raíz: `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`, `pnpm e2e`.
- `npm` workspaces es alternativa aceptable si pnpm no está disponible en el runner; **no se usan ambos** (un solo gestor, decidido en foundation).

---

## 5. Convenciones de nombres

| Objeto | Convención | Ejemplo |
|---|---|---|
| Directorio de servicio/app/paquete | `kebab-case` | `market-data`, `admin-shell` |
| Módulo Python importable | `snake_case` (derivado del dir) | `services/market-data` → `market_data` |
| Paquete PyPI-less interno | `platform_<nombre>` | `platform_kernel` |
| Paquete npm interno | `@platform/<nombre>` | `@platform/ui` |
| Imagen Docker | `platform/<servicio>:<tag>` | `platform/ledger:dev` |
| Schema PostgreSQL | `snake_case` = nombre del servicio | `market_data`, `identity` |
| Usuario DB por servicio | `<servicio>_svc` | `ledger_svc` |
| Claves Redis | `<servicio>:<sub>:<id>` | `identity:session:<sid>` |
| Topics Redpanda | `<dominio>.<entidad>.<evento>` (ver catálogo) | `identity.user.registered` |
| API pública | `/v1/...` en el path; versión = contrato | `POST /v1/auth/login` |
| Evento | `PascalCase` + `schema_version` entero | `UserRegistered` v1 |
| IDs expuestos | UUIDv7 (nunca secuenciales) | `0192…` |
| Archivos de docs phase0 | `<LETRA>-kebab-title.md` | `M-tech-stack.md` |
| ADR | `ADR-NNNN-<titulo-kebab>.md` | `ADR-0002-estrategia-de-descomposicion.md` |
| Migración Alembic | por servicio, cadena propia | `rev_8f3a1c2d4e5f` |

---

## 6. Política de shared packages

1. **Prohibido importar código entre servicios directamente.** `services/trading` no puede `import ledger...` ni copiar sus modelos; la interacción es **API versionada (HTTP/JSON) + eventos Redpanda** (00 §3).
2. Todo lo compartido vive en `packages/` y debe ser **transversal y sin dominio**: infraestructura técnica (config, logging, errores, outbox, idempotency, dinero, tiempo) o artefactos de contrato/UI.
3. **Nunca en `packages/`**: reglas de negocio, modelos/entidades de un servicio, queries SQL, políticas de autorización de un servicio, DTOs escritos a mano (van en contratos y se generan).
4. Todo paquete compartido tiene `README` con propósito, owner, política de cambios y **quién puede consumirlo**; los cambios en `platform-kernel` o `platform-contracts` requieren revisión de su owner + notificación a consumidores en el PR.
5. `platform-kernel` se mantiene **deliberadamente pequeño**; si dos servicios necesitan lógica de negocio común, eso es una señal de **duplicar o replantear el límite de dominio**, no de crear un "shared domain".
6. Un paquete que solo consume un único servicio **no es compartido**: se mantiene dentro de ese servicio.
7. Las dependencias de `packages/` se mantienen mínimas; añadir una dependencia a un paquete compartido equivale a añadirla a todos los consumidores.

---

## 7. Versionado de contratos

| Artefacto | Fuente | Versionado | Regla de cambio |
|---|---|---|---|
| API REST | `packages/platform-contracts/openapi/<servicio>.yaml` | Path `/v1` + SemVer del paquete de contratos | **Aditivo** sin bump de mayor (campos opcionales nuevos); **breaking** (borrar/cambiar tipo/renombrar campo obligatorio) = bump mayor + guía de migración + política `Sunset` en el anterior (REQ-040, REQ-088, BUILD-016) |
| Eventos | `packages/platform-contracts/events/<Evento>.json` | `event_type` + `schema_version` entero incremental | Preferir **additivo** (campo nuevo opcional); `schema_version` no soportada ⇒ consumidor log/skip (nunca DLQ); breaking estructural ⇒ **nuevo `event_type`** (P-event-catalog) |
| Clientes | `packages/api-client`, `packages/types` | Se **generan** desde contratos en CI | Prohibida edición manual; CI falla si la generación produce diff no commiteado |
| `CHANGELOG.md` | `packages/platform-contracts` | Entrada por PR | Todo PR que toque contratos añade entrada clasificada: `compatible` / `breaking` |

Validación en CI: (1) lint de OpenAPI, (2) test de contrato productor (implementación ⇒ spec), (3) test de contrato consumidor (spec ⇒ cliente), (4) detección de breaking cambio sin bump mayor ⇒ **fallo del pipeline**.

---

## 8. Migraciones por servicio

1. **Un servicio = una cadena de migraciones propia**: `services/<svc>/alembic.ini` + `services/<svc>/migrations/` con su propio `alembic_version`. Sin cadena compartida ⇒ sin orden entre servicios y sin bloqueos cruzados.
2. **Alcance**: solo tocan el schema de ese servicio (`search_path` fijado al schema propio). **Prohibido** referenciar tablas de otro schema (00 §3).
3. **Usuario**: migraciones corren como `<servicio>_svc` con `GRANT USAGE, CREATE ON SCHEMA <svc>`; si la migración necesita más privilegios, es un evento a revisar.
4. **Tipos**: dinero `NUMERIC(38,18)`, `timestamptz` UTC, UUIDv7, enums de negocio como tablas de referencia (`O-database-strategy.md` §3). CI inspecciona los tipos de las migraciones nuevas.
5. **CI por migración**: contra PostgreSQL efímero (testcontainers/compose perfil test) → `upgrade head` + `downgrade base` + `upgrade head` de nuevo. Migración sin downgrade razonable ⇒ justificación explícita en el PR.
6. **Runtime**: las migraciones se ejecutan como **job init** antes del rollout del nuevo código (K8s) o paso previo en compose; nunca "al arrancar el servidor" en múltiples réplicas a la vez.
7. **Compatibilidad**: la migración se mergea **antes o junto con** el código que la usa, en modo compatible (expand/contract) para permitir rollback sin pérdida de datos.
8. **Agregación**: `scripts/migrate-all.py` itera los servicios para entornos locales; en producción cada servicio migra el suyo (dueño = owner del servicio).

---

## 9. Reglas de aislamiento entre servicios

| # | Regla | Evidencia en CI |
|---|---|---|
| 1 | **Sin imports cruzados**: un servicio no importa módulos de otro (`platform-kernel` y contratos generados son la única excepción, vía `packages/`). | `ruff`/`import-linter` (Python) + `no-restricted-imports` (ESLint); fallo bloquea el PR (REQ-077) |
| 2 | **Sin acceso a datos cruzado**: cada servicio usa su schema y su usuario; ninguna tabla de otro schema. | Test de integración que intenta consultar schema ajeno ⇒ debe fallar |
| 3 | **Comunicación solo por API versionada + eventos**; sin bus de mensajes privado ni colas por servicio fuera de Redpanda. | Revisión + arquitectura; sin dependencias directas entre paquetes de servicios |
| 4 | **Sin joins entre servicios**; composición en el front o en un BFF (`gateway`, `admin`), nunca consultas distribuidas. | Regla de diseño + tests de contrato |
| 5 | **Estado compartido prohibido**: nada de claves Redis ajenas, archivos compartidos ni caché entre servicios; Redis namespaced `<svc>:`. | Code review + test de claves |
| 6 | **Eventos solo vía transactional outbox** con el envelope del catálogo; ningún servicio publica "a mano" tras hacer commit. | Test BUILD-013: evento no pareado a transacción ⇒ falla |
| 7 | **Llamadas síncronas**: solo al API público del destino, con timeout explícito y reintento **solo** en operaciones idempotentes; sin cadenas largas de salto (preferir evento cuando el destino no es inmediato). | Revisión de arquitectura + tests de timeout |
| 8 | **Sin modelos de dominio compartidos**: cada servicio modela lo suyo; lo común es contrato (`platform-contracts`), no clase Python. | import-linter + revisión |
| 9 | **Despliegue independiente**: cada servicio tiene su Dockerfile, sus healthchecks, su SLO y su rollout; nada asume orden de arranque entre servicios (arranque tolerante a fallos). | K8s manifests + compose healthchecks |
| 10 | **Nuevos servicios solo con criterios de ADR-0002** (límite de dominio, escalado independiente medible, tolerancia a fallos no global, equipo independiente) — nunca por moda. | ADR obligatorio en el PR que añade un servicio |

---

## 10. Definición de "frentes" del repo (Definition of Done estructural)

Un PR que toque la estructura debe cumplir:

- [ ] La violación de frontera (import/DB cross-service) **falla** el CI (BUILD-001).
- [ ] Cambio de contrato ⇒ entrada en `platform-contracts/CHANGELOG.md` + tests de contrato verdes.
- [ ] Cambio de schema ⇒ migración con upgrade/downgrade verdes y tipos correctos.
- [ ] Nuevo servicio ⇒ ADR-0002, Dockerfile, healthchecks, dashboards/alertas mínimo, runbook.
- [ ] `CODEOWNERS` actualizado si se añade directorio nuevo.
- [ ] Docs afectadas actualizadas (REQ-076): `docs/phase0`/ADR/runbook según corresponda.

---

Ver también: `00-decisions.md` §3 (catálogo de servicios), `M-tech-stack.md` (elecciones y dependencias), `O-database-strategy.md` (schemas/owners), `P-event-catalog.md` (envelope de eventos), `W-build-now.md` (BUILD-001, BUILD-016, BUILD-017).
