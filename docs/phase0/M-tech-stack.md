# M — Stack Tecnológico (justificación y alternativas descartadas)

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `[PROJECT_NAME]` · Dominio: `[DOMAIN]` · Marca: `[BRAND_NAME]`

Fuente de verdad: `docs/phase0/00-decisions.md` §4. Este documento **detalla y justifica** la decisión ya tomada; no la modifica. En caso de conflicto prevalece `00-decisions.md`. ADR relacionados: ADR-0001 (monorepo), ADR-0003 (microservicios y lenguaje de latencia crítica), ADR-0005 (datos/ledger), ADR-0007 (Redpanda/outbox), ADR-0009 (auth), ADR-0011 (idempotencia).

Toda versión listada es **versión objetivo fijada en lockfile** (`uv.lock`, `pnpm-lock.yaml`) al momento de implementar; la cifra exacta se congela en la PR de foundation y de ahí en adelante solo cambia por PR de renovación (§11).

---

## 1. Principios de selección del stack

1. **Sin lenguajes ni frameworks adicionales sin evidencia medida** (ADR-0003): se acepta un segundo lenguaje solo con benchmark que demuestre incumplimiento de SLO con el lenguaje actual ya optimizado.
2. **Estándar abierto sobre propietario**: OpenTelemetry, OpenAPI, Kafka API, S3 API, OpenTelemetry→Prometheus/Grafana/Loki/Tempo. Sin atadura a un cloud concreto en Fase 1.
3. **Dinero primero**: cualquier elección se evalúa contra ACID, `Decimal`/`NUMERIC(38,18)`, idempotencia y auditabilidad (`00-decisions.md` §5, §7).
4. **Regla de no-ficción**: lo que requiere proveedor/licencia queda como interface + adapter + mock + placeholder (`00-decisions.md` §10): object storage productivo, Vault/KMS, feeds, PSP, KYC.
5. **Un stack, dos superficies de trabajo**: TypeScript para frontend/contratos, Python para servicios de dominio. No más lenguajes en Fase 1.

---

## 2. Frontend

| Elección | Detalle |
|---|---|
| **Next.js 15 (App Router)** | SSR/SSG para contenido público con requisito SEO (landing, catálogo de símbolos, páginas legales), React Server Components para reducir JS en cliente, routing por carpetas alineado con `apps/web` y `apps/admin-shell`, i18n/RTL viable con i18n de comunidad, `instrumentation.ts` para OpenTelemetry del lado servidor. |
| **React 19 + TypeScript estricto** | `strict: true`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `noImplicitAny`. El typing estricto es control de calidad en dinero: impide mezclar `number` en operaciones que deben ser `Decimal`/string. |
| **Tailwind CSS** | Tokens de diseño en `packages/ui`, utilidades en lugar de capas de CSS framework, fácil theming/RTL, sin runtime CSS-in-JS en el servidor. |
| **Design system propio en `packages/ui`** | Componentes, tokens, iconografía y copy propios: garantiza identidad visual legalmente independiente (`00-decisions.md` §2), consistencia web/admin y evita dependencia de librerías de UI con identidad reconocible. |
| **WebSockets** | Streaming de cotizaciones/estado (Fase 3, servicio `market-data`) y notificaciones in-app: conexión persistente gateway↔cliente, con `sequence`+heartbeat y resync snapshot+delta (`W-build-now.md` BUILD-029). El servidor de WS vive en backend; el frontend solo consume. |
| **PWA** | Instalable en móvil/escritorio, shell offline para el estado de la app, base para push (adapters de `notification`; push real = `PENDIENTE`/proveedor). |

### 2.1 Alternativas descartadas (frontend)

| Alternativa | Motivo de descarte |
|---|---|
| **Vite + SPA pura (React)** | Sin SSR/SSG: el contenido público (SEO, sharing, first paint) queda en cliente, exige BFF/SSR aparte más adelante; más JS inicial; no resuelve caching de borde. Vite se conserva como bundler interno si Next lo permite en librerías. |
| **Remix / React Router 7 en modo framework** | Ecosistema y hiring menores, RSC menos maduro, adapters propietarios históricos, menor resolución de problemas en comunidad frente a Next. Añade riesgo sin beneficio medible para este caso. |
| **Angular** | Opinionado y pesado para un greenfield con equipo pequeño; peor integración con Tailwind/design system propio; TypeScript completo pero con más convención impuesta; velocidad de iteración menor en UI de trading. |
| **Svelte/SvelteKit** | Ecosistema de componentes y tooling menor para PWA/WS/i18n en este dominio; riesgo de hiring. Se reevaluaría solo con evidencia (no aplica en Fase 1). |

---

## 3. Backend

| Elección | Detalle |
|---|---|
| **Python 3.13** | `asyncio.TaskGroup` (concurrencia estructurada, `ExceptionGroup`), rendimiento de runtime mejorado, madurez del ecosistema cuantitativo/data (necesario para `market-data`, `trading`, `risk` en fases posteriores). |
| **FastAPI** | Nativo async (Starlette), validación y OpenAPI generados desde el mismo modelo Pydantic → contrato único sin duplicación, DI ligera, buena instrumentación OTel, el framework async más productivo de Python. |
| **Pydantic v2** | Núcleo en Rust (`pydantic-core`) → validación rápida; modo `strict` para payloads financieros; discriminados/union types para envelope de eventos y respuestas tipadas. |
| **SQLAlchemy 2 async + Alembic** | Estilo 2.0 tipado, async sobre psycopg/asyncpg, `NUMERIC(38,18)` → `Decimal`; Alembic = migraciones versionadas por servicio (`N-monorepo-structure.md` §8). |
| **asyncio / TaskGroup** | Consumidor de outbox, relay a Redpanda, broadcast WS y timeouts se escriben con concurrencia estructurada: sin `create_task` huérfanos, cancelación y cierre ordenados. |

### 3.1 Alternativas descartadas (backend)

| Alternativa | Motivo de descarte |
|---|---|
| **Django / DRF** | Orientado a monolito sync; async maduro solo parcialmente (Views ASGI, ORM async limitado); admin innecesario (el backoffice es un BFF propio en Fase 7); peso y opiniones no justificados para 13 microservicios finos. |
| **Node.js / NestJS** | Añade un segundo runtime de servicio con otro modelo de error/typing/distinto manejo de `Decimal` para dinero; NestJS es productivo pero su DI/opiniones no aportan frente a FastAPI en este caso; el requisito de stack es Python (00 §4). |
| **Go** | Rendimiento excelente, pero iteración más lenta en lógica de dominio compleja, ecosistema cuantitativo inexistente, y **añadiría lenguaje sin evidencia** → exactamente lo que prohíbe ADR-0003 (§4). Candidato único a reintroducir si el benchmark lo justifica. |
| **Java / Spring** | Overhead JVM (arranque, memoria, imagen) en muchos contenedores pequeños, toolchain más pesado para el equipo, sin ventaja de ecosistema que compense en Fase 1. |
| **gRPC como API principal** | OpenAPI/REST+JSON es el contrato único con clientes públicos (REQ-040) y con el frontend; gRPC añadiría un segundo contrato y tooling. Se descarta como API externa; intra-servicio solo HTTP/JSON en Fase 1 (00 §4: sin malla de servicios). |

---

## 4. Lenguaje de latencia crítica: por qué NO Rust/Go en Fase 1 (ADR-0003)

**Decisión**: Fase 1 corre 100 % en Python 3.13. No se introduce Rust ni Go.

**Motivos**:
1. **No hay hot spot medido todavía.** El código que existe es foundation (gateway, identity, audit): I/O-bound sobre PostgreSQL/Redis/Redpanda, no cómputo-bound. Optimizar sin perfil es especulación.
2. **Costo de segundo lenguaje**: toolchain, imágenes base, pipeline CI duplicado, contratos FFI/IPC entre lenguajes, dos curvas de observabilidad (instrumentación OTel por runtime), y duplicidad de controles de seguridad. Ese costo solo se paga con beneficio demostrable.
3. **Riesgo de dispersión**: introduce dos formas de modelar dinero (`Decimal` vs `f64`) y dos superficies de error en el camino financiero, justo donde `00-decisions.md` §5 exige una sola vía verificable.
4. **El presupuesto de latencia aún no está validado**: los SLO de §7.1 son objetivos borrador a confirmar con benchmark; no se optimiza contra un número no medido.

**Benchmark obligatorio que justificaría introducir Rust/Go (condiciones cumulativas)**:

| # | Condición |
|---|---|
| 1 | Existe un componente identificado como cuello de botella **por perfilado** (no por intuición) en el camino caliente. |
| 2 | La implementación Python ya aplicó optimizaciones guiadas por perfil: caché, batching/pipelining, reducir allocations, `pydantic-core`, vectorización/numpy, evitar N+1, compaction de payloads. |
| 3 | Bajo carga sintética realista (k6/locust, datasets propios, concurrencia proyectada del pico por fase) el componente **incumple el SLO candidato** de §7.1 (p95/error-rate) o excede el umbral de coste aceptado de CPU por réplica. |
| 4 | El resultado se reproduce en 2 ejecuciones independientes y se archiva como artefacto (informe + script de carga + perfil) **en el ADR** (`docs/adr/ADR-0003-*`). |
| 5 | El ADR propone el alcance mínimo (solo ese componente), la estrategia de contrato (mismo OpenAPI/eventos), la estrategia de despliegue y la estimación de coste operativo. |

**Si se aprueba**: el componente se aísla tras su API/versionado ya existente (nada cambia para consumidores) y convive con Python; no se migra el servicio completo. Umbrales numéricos concretos: **se fijan con el primer benchmark de Fase 1** (`W-build-now.md` BUILD-032) y se documentan en ADR; hoy son `POR VALIDAR`.

---

## 5. Datos

| Elección | Detalle |
|---|---|
| **PostgreSQL 17** | ACID para dinero, `NUMERIC(38,18)` + `Decimal`, transacciones fuertes + outbox en la misma transacción, un **schema por servicio** (`identity`, `audit`, …) sin acceso cruzado (00 §3, ADR-0005), particionado/retención (Fase 2 BUILD-025), madurez operativa. |
| **Redis 7** | Sesiones/denylist de refresh, rate limiting por IP y cuenta, caché de lecturas. **Nunca fuente de verdad** (pérdida por reinicio aceptable, TTL documentado). Claves con namespace `<servicio>:…`. |
| **Redpanda (API Kafka)** | Log duradero, replay, reintentos y DLQ compatibles con ecosistema Kafka; binario único sin JVM/ZooKeeper → compose y K8s más simples que Kafka puro; base del transactional outbox (ADR-0007). |
| **TimescaleDB (diferido, Fase 3+)** | Extensión sobre PostgreSQL para hypertables/compresión de ticks y velas. **Criterio de activación**: cuando el volumen de ticks particionado en PostgreSQL 17 puro incumpla el presupuesto medido de ingest/consulta en benchmark (BUILD-032), se activa por ADR sin cambiar de motor. |
| **ClickHouse (diferido, Fase 7+)** | OLAP para reporting/backtesting sobre histórico grande. **Criterio de activación**: consultas analíticas p95 > objetivo sobre datos que ya no caben razonablemente en PostgreSQL con particionado, medido; además exige pipeline de carga documentado y owner. |
| **S3-compatible** | Fase 1: MinIO en compose (local) como placeholder de la API S3. Producción: `REQUIERE PROVEEDOR` (00 §4). Uso: documentos KYC, reportes, backups. |

### 5.1 Alternativas descartadas (eventos)

| Alternativa | Comparación | Motivo de descarte en Fase 1 |
|---|---|---|
| **NATS JetStream** | Más simple y ligero; at-least-once, consumo por sujeto. | Menor valor de replay histórico y menor ecosistema de conectores/monitoring compatibles con Kafka; migrar luego a Kafka API reescribiría consumidores. Redpanda ya da la API Kafka sin el peso de Kafka. |
| **Kafka puro (Apache)** | Mismo modelo, ecosistema máximo. | JVM + KRaft + partes múltiples (broker/ZK-histórico/Connect/schema-registry) → mayor coste operativo y arranque en compose/CI para una Fase 1 con pocos tópicos. Redpanda conserva la compatibilidad de API con menor superficie operativa. |
| **Cola simple (Redis Streams/RabbitMQ)** | Muy fácil de montar. | Semántica de replay/retención/consumidores múltiples más débil para outbox + auditoría + múltiples consumidores; se reservaría solo si Redpanda quedara inviable (no es el caso). |

> El catálogo de eventos y el envelope (`event_id`, `event_type`, `schema_version`, `correlation_id`, `causation_id`, …) viven en `docs/phase0/P-event-catalog.md` y se materializan en `packages/platform-contracts` (ver `N-monorepo-structure.md` §7).

---

## 6. Infraestructura

| Elección | Detalle |
|---|---|
| **Docker + docker compose (local)** | `infrastructure/compose`: PostgreSQL 17, Redis 7, Redpanda, MinIO, OTel Collector + stack de observabilidad, con healthchecks; `compose up` levanta toda la foundation (BUILD-002). Imágenes multi-stage, no-root, SBOM (BUILD-005). |
| **Kubernetes manifests preparados (kustomize)** | `infrastructure/kubernetes/base` + `overlays/` con valores placeholder: **preparados, no aplicados** en Fase 1 (no hay cluster/proveedor). Kustomize (nativo de `kubectl`) evita plantillas extra. |
| **Terraform (solo estructura)** | `infrastructure/terraform` con módulos/variables/outputs y `terraform validate` en CI; **sin backend remoto, sin estado, sin credenciales** en el repo. Provisión real = `REQUIERE PROVEEDOR` con credenciales. |
| **GitHub Actions** | Integración nativa con el monorepo: triggers por path-filter por servicio, matrices, caché de dependencias, gates de lint/type/test/contract, secret-scan y SBOM. |
| **Registro de imágenes** | El asociado al repositorio en GitHub Actions; si se exige otro: `REQUIERE PROVEEDOR`. Localmente compose construye `platform/<servicio>:dev`. |

---

## 7. Observabilidad

| Elección | Detalle |
|---|---|
| **OpenTelemetry** | Estándar abierto, sin vendor lock-in. Instrumentación automática para FastAPI/Starlette/SQLAlchemy/psycopg y para Next.js (`instrumentation.ts` + OTel Node SDK). Contexto propagado: `trace_id`, `request_id`, `correlation_id` (00 §7). |
| **Prometheus** | Métricas RED (rate/errors/duration) por servicio, scraping del stack en compose/K8s. |
| **Grafana** | Dashboards RED por servicio + SLO; única consola de consulta. |
| **Loki** | Logs indexados por labels (`service`, `env`, `request_id`), retención configurable. |
| **Tempo** | Trazas distribuidas gateway→servicio→outbox→consumidor. |

### 7.1 SLI/SLO propuestos (objetivos a validar con benchmarks)

> Estado: **borrador `POR VALIDAR`**. Se confirman (o ajustan) con el primer benchmark de carga (BUILD-032) antes de fijarse como gate de CI.

| SLI | Fórmula | SLO candidato (borrador) | Medición |
|---|---|---|---|
| Latencia API (gateway) | p95 de duración HTTP por ruta, exclude 5xx no aplicable | p95 ≤ 300 ms en rutas de lectura bajo carga nominal | Histogramas OTel→Prometheus |
| Error rate | 5xx / total de peticiones (por servicio) | ≤ 0,5 % mensual | Prometheus |
| Disponibilidad gateway | peticiones no 5xx+no 503 / total | ≥ 99,9 % mensual | Prometheus |
| Auth success/latency | p95 login + tasa de fallos inesperados | p95 ≤ 500 ms; alerta ante anomalía | Prometheus + Loki |
| Freshness market-data (Fase 3) | edad del último tick publicado | p99 ≤ 1 s (borrador) | Métrica del productor |
| Backlog outbox | eventos sin publicar con antigüedad > T | 0 con antigüedad > 60 s | Métrica del relay |

Alertas: burn-rate multiventana para disponibilidad/errores; nunca alerta sin dashboard y runbook (`docs/runbooks/`).

---

## 8. Secrets

- **Local**: variables de entorno vía `.env` **no commiteado** (`.env.example` con placeholders), inyectado por compose. Nada de secretos en repo, logs, frontend ni documentación (00 §7).
- **CI**: secretos en GitHub Actions Secrets; nunca en logs ni en artefactos; secret-scan como gate (p. ej. gitleaks) (BUILD-005).
- **Producción**: **Vault/KMS → `REQUIERE PROVEEDOR`** (00 §4). La aplicación solo conoce la interfaz `SecretProvider` (leer por nombre, rotación), de modo que el cambio de proveedor no toca código de dominio. Rotación documentada en runbook antes de LIVE.

---

## 9. Testing y calidad

| Nivel | Elección | Uso |
|---|---|---|
| Unitario | **pytest** + **pytest-asyncio** | Dominio puro, sin red; rápido en CI por servicio. |
| Integración | **testcontainers** (o `compose` con perfil de test) | PostgreSQL real, Redis, Redpanda: migraciones, outbox, idempotencia. |
| Invariantes | **hypothesis** | Propiedades financieras adversariales: suma de entradas = 0, sin `float`, idempotencia ante reintentos, redondeo determinista (BUILD-024). |
| Contrato | OpenAPI + eventos desde `platform-contracts` | Romper el contrato falla el PR (REQ-088, BUILD-016). |
| E2E | **Playwright** | Flujos DEMO en navegador (registro, login, MFA, wallet) contra compose; captura de evidencia. |
| Carga | **k6** (preferido; locust como alternativa a evaluar) | p95/throughput por servicio y WS; base del benchmark ADR-0003 (BUILD-032). |
| Lint/type | **ruff** (format+lint), **mypy** estricto, **ESLint**, **tsc --noEmit** | Gates en CI; ruff/ESLint con reglas de frontera (sin imports entre servicios). |
| Seguridad estática | secret-scan, escaneo de CVE de dependencias (§11), SBOM por imagen | BUILD-005. |

---

## 10. Tabla resumen

| Capa | Elección | Versión objetivo | Alternativa descartada | Motivo | Riesgo |
|---|---|---|---|---|---|
| Frontend framework | Next.js 15 App Router + React 19 | Next 15.x / React 19.x | Vite+SPA, Remix, Angular | SSR/SEO público, ecosistema, RSC | Cambios de API en App Router/RSC |
| Estilos/design system | Tailwind + `packages/ui` propio | Tailwind 4.x (3.x si incompatibilidad) | UI kit de terceros, CSS-in-JS | Identidad propia, tokens, RTL | Deriva de tokens sin gobernanza |
| Lenguaje cliente | TypeScript estricto | TS 5.x | JS sin tipos | Errores tempranos en dinero/UI | — |
| Lenguaje servicios | Python 3.13 | 3.13.x | Node/Nest, Go, Java/Spring, Django | Ecosistema cuantitativo, async, stack decidido | GIL en cómputo puro → benchmark ADR-0003 |
| API framework | FastAPI + Pydantic v2 | FastAPI 0.11x / Pydantic 2.x | Django DRF, Flask, gRPC | OpenAPI automático, async, validación estricta | Dependencia de un maintainer principal |
| ORM/migraciones | SQLAlchemy 2 async + Alembic | 2.0.x / Alembic 1.x | SQLModel, peewee, raw SQL | Tipado, async, madurez | Migraciones manuales mal revisadas |
| BD transaccional | PostgreSQL 17 | 17.x | MySQL, MongoDB, SQL distribuido gestionado | ACID/`NUMERIC`, schemas aislados | Configuración de réplicas/backup pendiente de proveedor |
| Cache/sesión/rate-limit | Redis 7 | 7.x | Memcached, CDN | Sesiones+denylist+rate limit en uno | No usarlo como fuente de verdad |
| Eventos | Redpanda (API Kafka) | última estable fijada, API Kafka ≥3.x | Kafka puro, NATS JetStream, Redis Streams | Replay duradero + operación ligera | Conocimiento operativo; retención mal dimensionada |
| Time-series | PostgreSQL (TimescaleDB diferido) | Fase 3+ | InfluxDB, ClickHouse ya | Sin motor extra hasta medir | Volumen de ticks subestimado |
| OLAP | ClickHouse (diferido) | Fase 7+ | OLAP en PostgreSQL | Escaneos columnar cuando se mida | — |
| Object storage | S3 API (MinIO local) | API S3; prod `REQUIERE PROVEEDOR` | FS local, GCS/Azure directo | Portabilidad de API | KYC docs sin bucket productivo |
| Edge/routing | `gateway` propio (FastAPI/Starlette) | Fase 1 | Kong/APISIX, nginx como gateway lógico | JWT/rate-limit/request-id con OTel y test propio | Reimplementar features de productos maduros |
| Frontend infra | Docker + compose | Compose spec | k8s kind obligatorio en local | Arranque `compose up` único | Divergencia local↔K8s |
| Orquestación | K8s manifests + kustomize (preparados) | k8s 1.3x cuando haya cluster | Solo compose, Helm | Portabilidad sin aplicar a la nube | Sin cluster real = no probado aún |
| IaC | Terraform estructura | TF 1.x, `validate` en CI | Pulumi, Ansible | Estructura sin credenciales/estado | No hay state real hasta proveedor |
| CI/CD | GitHub Actions | actions actuales (pinned por SHA) | GitLab CI, Jenkins | Nativo del monorepo | Lock-in de runners; mitigado con pasos reemplazables |
| Observabilidad | OTel + Prometheus + Grafana + Loki + Tempo | colección estable fijada | APM SaaS con agentes propietarios | Estándar abierto, sin vendor | Curva de configuración del collector |
| Secrets | env local → Vault/KMS `REQUIERE PROVEEDOR` | prod: por definir | secretos en repo | 00 §7 | Rotación pendiente antes de LIVE |
| Testing | pytest, hypothesis, testcontainers, Playwright, k6 | fijados en lockfile | solo unitarios, Jest | Pirámide completa (REQ-073) | Coste de tiempo de CI |
| Calidad | ruff + mypy estricto + ESLint + tsc | fijados | solo lint básico | Gates automáticos | Falsos positivos → reglas calibradas |

---

## 11. Madurez y riesgo del stack

| Área | Madurez | Riesgo | Mitigación |
|---|---|---|---|
| Python async (FastAPI + SQLAlchemy 2 async) | Alta, pero async sigue siendo fácil de romper (bloqueos accidentales, sesiones compartidas) | Deadlocks de sesión, bloqueo del event loop | mypy estricto, reglas de sesión por request, tests de concurrencia, revisión de `await` en hot path |
| Next.js App Router/RSC | Alta con churn de APIs entre majors | Cambios RSC/serialización | Versión fijada, upgrades por PR con E2E Playwright |
| Redpanda/Kafka semantics | Alta en el modelo; operación menos difundida que Postgres | Retención/consumer groups mal configurados | Runbooks, DLQ + backoff (BUILD-013), métricas de lag |
| PostgreSQL multicapa (13 schemas) | Alta | Grants mal configurados → acceso cruzado | Usuario por servicio + `DEFAULT PRIVILEGES`, test de aislamiento en CI |
| K8s/Terraform "preparados pero no aplicados" | Media (no ejecutados en Fase 1) | YAML/HCL que no compila en un cluster real | `kubectl --dry-run=client`, `kustomize build`, `terraform validate` en CI; revisión al primer cluster |
| Design system propio | Baja al inicio | Inconsistencia/inaccesibilidad | Tokens únicos en `packages/ui`, checklist a11y, storybook-like catálogo (cuando se autorice) |
| Seguridad (auth propia) | Crítica | Implementación defectuosa de JWT/Argon2id | Tests negativos, librerías establecidas, threat model en fase 0, revisión antes de LIVE |
| Riesgo de cadena de suministro | Media | Dependencias comprometidas | Lockfiles + pin de actions por SHA + CVE scan + SBOM |

**Factor humano**: el stack es amplio para un equipo pequeño; se prioriza que cada fase añada superficie solo cuando su servicio se active (Fase 1 = gateway/identity/audit + foundation).

### 11.1 Política de actualización de dependencias

1. **Fijado (pin)**: todo queda fijado — `uv.lock` (Python, con `uv`), `pnpm-lock.yaml` (TS), imágenes Docker por digest en compose/K8s base, `uses:` de GitHub Actions por SHA.
2. **Renovación programada**: Dependabot (nativo de GitHub, sin proveedor adicional) genera PRs semanales por ecosistema (pip/uv, npm, actions, Docker); actualizaciones de **patch/minor** se mergean si CI verde; **majors** requieren PR dedicada con changelog, tests verdes y, si toca contrato/datos/seguridad, ADR o revisión del owner del área.
3. **Escaneo de vulnerabilidades**: en cada PR y semanal — vulnerabilidades de dependencias (Python/npm), escaneo de imágenes, secret-scan. Bloqueo por CVE crítica en componente con exploit; alta → plan en ≤7 días; media → siguiente ventana de renovación. Resultados y SBOM como artefactos de CI.
4. **Caducidad**: ninguna dependencia sin actualizar > 90 días sin justificación registrada; dependencias abandonadas se sustituyen por ADR.
5. **Congelación en caliente**: durante una fase en curso solo se aceptan cambios de dependencia que arreglen seguridad o bloqueen el desarrollo; el resto espera a la ventana de la fase.

---

Ver también: `N-monorepo-structure.md` (estructura y fronteras), `O-database-strategy.md` (schemas y tipos), `P-event-catalog.md` (contratos de eventos), `W-build-now.md` (qué se construye en Fase 1).
