# ADR-0001 — Monorepo único frente a multirepo

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **ADR relacionados:** ADR-0002 (descomposición), ADR-0004 (contratos), ADR-0005 (datos por servicio)

## Contexto

`[PROJECT_NAME]` es greenfield. La Fase 1 solo implementa `gateway`, `identity` y `audit`, pero el catálogo canónico prevé 13 servicios, dos aplicaciones frontend (`apps/web`, `apps/admin-shell`) y paquetes compartidos (`platform-kernel`, `platform-contracts`, `api-client`, `types`, `ui`, `config`, `security`).

Hechos que condicionan la elección:

1. **Contratos multi-consumidor**: la spec OpenAPI y los esquemas de eventos deben cambiar en la misma PR que su productor, sus consumidores y el cliente generado. Con repos separados eso exige sincronización manual de versiones y una matriz de compatibilidad entre 13 servicios y el frontend.
2. **Fronteras de dominio verificables**: la prohibición de imports cruzados y de acceso a datos de otro servicio solo es automatizable si un único pipeline puede inspeccionar todos los árboles (`N-monorepo-structure.md` §9).
3. **Equipo pequeño en Fase 1**: no existe ningún equipo independiente que justifique un repo por equipo.
4. **Coste operativo**: un solo conjunto de secretos de CI, una branch protection, un lockfile por ecosistema, un set de ADRs y de `docs/`.

También son conocidos los costes del monorepo: CI que crece con el tamaño del repo, mayor blast radius de cada merge, permisos finos más difíciles y checkout más pesado.

## Decisión

Se adopta un **monorepo único** con la estructura fijada en `docs/phase0/N-monorepo-structure.md` §2:

- `apps/` (frontend desplegable), `services/` (un bounded context por servicio), `packages/` (compartido sin despliegue), `infrastructure/` (compose, kubernetes, terraform, monitoring), `docs/`, `scripts/`, `tests/` (contract/e2e/invariantes/load) y `.github/`.
- **Workspaces**: uno de Python con `uv` (`pyproject.toml` raíz + `uv.lock` único, `members = ["services/*", "packages/platform-kernel"]`) y uno de TypeScript con `pnpm` (`pnpm-workspace.yaml` + `pnpm-lock.yaml` único). Un solo gestor por ecosistema.
- **CI con path filters**: cada workflow corre solo sobre las rutas afectadas; caché por lockfile; matrices por servicio. Gates obligatorios: ruff/mypy, ESLint/tsc, tests de servicio, contract tests, lint de fronteras, secret-scan y SBOM.
- **Fronteras en CI**: `import-linter`/reglas de ruff y ESLint `no-restricted-imports` hacen fallar la PR ante un import entre servicios; un test de integración verifica que un servicio no puede consultar el schema de otro.
- **Permisos**: `CODEOWNERS` por `services/<nombre>/`, `packages/` e `infrastructure/`.
- **Checkout**: sparse/checkout selectivo en jobs que solo necesitan un subárbol.
- **Sin herramienta de build de monorepo (Bazel/Nx/Turborepo) en Fase 1**: los workspaces nativos y los path filters bastan para el tamaño actual; se reconsidera solo si el tiempo de CI medido deja de escalar.

## Consecuencias

### Positivas

- Cambios atómicos: contrato + productor + consumidor + cliente se mergean en una sola PR.
- El `api-client` y los tests de contrato se generan y validan en el mismo CI que el servicio: imposible quedar desincronizado.
- Las reglas de aislamiento entre servicios se aplican en un único pipeline y fallan el PR.
- Un solo versionado de Python/Node/TS/linters: sin deriva de configuración entre repos.
- Reutilización sin versionado frágil: `packages/` se consumen por workspace local, sin publicar en registry.
- Un árbol, un `docs/`, un set de ADRs: onboarding y descubrimiento del sistema completo.
- Menor coste operativo: 1 repo, 1 conjunto de secretos de CI, 1 configuración de rama.

### Negativas

- El CI crece con el repo; mitigado con path filters y caché por lockfile, pero hay que vigilarlo (medirlo es el criterio de reevaluación).
- Un merge defectuoso puede afectar a varios servicios a la vez; mitigado con tests por servicio, gates de contrato y `CODEOWNERS`.
- Permisos finos por equipo limitados a directorios, no a repos; irrelevante mientras haya un solo equipo.
- Checkout y clonado más pesados; mitigado con sparse checkout y artefactos por servicio.
- Riesgo de acoplamiento accidental entre servicios (imports de conveniencia); mitigado con lint bloqueante y revisión.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **Multirepo (uno por servicio)** | Sincronización manual de contratos, matriz de versiones entre 13 repos + frontend, 13 conjuntos de secretos/branch protection, y ningún equipo independiente que lo exija. Se reconsidera solo si aparece un equipo/proceso realmente independiente o si el CI deja de escalar tras medirlo. |
| **Dos repos (frontend + backend) con contratos publicados en registry** | Añade el problema de versionado de contratos precisamente donde más duele (productor/consumidor en lenguajes distintos), sin eliminar el problema de sincronización entre servicios. |
| **Monorepo + Bazel/Nx/Turborepo** | Complejidad de configuración y curva de aprendizaje no justificadas con pocos paquetos; se reserva para cuando el tiempo de CI medido lo exija. |
| **Monorepo + git submódulos por servicio** | Peor experiencia de PR atómica y más fricción que el workspace nativo; sin beneficio medible. |

## Referencias

- `docs/phase0/00-decisions.md` §3 (catálogo de servicios y aislamiento), §4 (GitHub Actions, workspaces).
- `docs/phase0/N-monorepo-structure.md` §1 (por qué monorepo), §2 (árbol), §4 (workspaces), §9 (reglas de aislamiento).
- `docs/phase0/M-tech-stack.md` §6 (CI/CD), §9 (testing y gates), §11 (renovación de dependencias).
- `docs/phase0/A-executive-summary.md` §4 (tabla de decisiones estructurales).
- `docs/adr/ADR-0002-estrategia-de-descomposicion.md`, `docs/adr/ADR-0004-api-first-y-contratos.md`, `docs/adr/ADR-0005-base-de-datos-por-servicio.md`.
