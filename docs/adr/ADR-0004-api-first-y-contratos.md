# ADR-0004 — API-first: OpenAPI como fuente única por servicio, cliente generado, contract tests y versionado `/api/v1` → `/api/v2`

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **ADR relacionados:** ADR-0001 (monorepo), ADR-0007 (eventos), ADR-0010 (idempotencia)

## Contexto

La plataforma tiene múltiples consumidores con ritmos distintos: PWA pública (`apps/web`), backoffice (`apps/admin-shell`), clientes generados en TypeScript y Python internos, y los propios servicios entre sí. Existe el riesgo clásico de deriva entre tres artefactos: el código FastAPI, la especificación publicada y el cliente consumidor. `Q-api-map.md` §4 y `N-monorepo-structure.md` §7 describen el diseño objetivo pero difieren en la ubicación literal de la spec canónica; hace falta una regla única.

Además, la API pública es la superficie donde un cambio mal hecho rompe clientes en producción: sin detección automática de breaking changes, cualquier PR puede romper un contrato sin que nadie lo note hasta el incidente.

## Decisión

### 1. OpenAPI 3.1 como fuente única, un archivo por servicio

- El servicio **dueño** de cada ruta publica su spec. **Solo existe una copia canónica**: `packages/platform-contracts/openapi/<servicio>.yaml` (registro único que consumen clientes, gateway y gates de CI).
- El artefacto `services/<svc>/openapi.yaml` (`Q-api-map.md` §4) es **generado** desde la implementación/exportación del servicio; el CI exige igualdad con la canónica. Divergencia = fallo de build.
- Toda ruta FastAPI (pública e interna) debe aparecer en la spec: ruta ausente ⇒ fallo de CI. No hay especificación paralela en wiki ni DTOs escritos a mano fuera de contratos.
- El gateway compone su superficie `/api/v1` a partir de las specs de los servicios (con `servers` `/api/v1`); las rutas internas viven bajo `/internal/v1` y jamás se enratan en el edge (404).
- La WS se especifica con AsyncAPI en `services/market-data/asyncapi.yaml` (BUILD-029, 2026-10-02), mismo principio de contrato único.

### 2. Generación de cliente

- `packages/api-client` (TS, público) y `packages/types` se **generan** desde `platform-contracts` en CI con marcador `// @generated`; edición manual prohibida y el pipeline falla si la regeneración produce un diff no commiteado.
- El cliente expone tipos, runtime de errores `application/problem+json`, manejo de `Idempotency-Key` y política de reintentos.

### 3. Contract tests (gates bloqueantes)

1. Lint de la spec (estilo, referencias íntegras, ejemplos válidos).
2. **Spec diff gate** contra la rama base: detección de breaking change; breaking sin bump de mayor ⇒ fallo.
3. Test productor: lo que implementa el servicio ⊆ lo que declara la spec.
4. Test consumidor: el cliente generado cumple la spec.
5. **Consumer-driven** obligatorio para rutas financieras (`orders`, `payments`, `ledger`) antes de merge.

### 4. Política de versionado

| Regla | Detalle |
|---|---|
| Público | Prefijo `/api/v1/{recurso}` servido solo por `gateway`; el major del path es el único artefacto que cambia por breaking change |
| Interno | `/internal/v1/…`, nunca expuesto en edge; los consumidores internos se actualizan antes de deprecar la versión pública equivalente |
| Cambio aditivo | Campo opcional con default, endpoint nuevo, query param opcional → sin bump de mayor |
| Breaking | Renombrar/eliminar/cambiar tipo de campo, hacer obligatorio lo opcional, cambiar semántica de status, eliminar endpoint, restringir scopes, cambiar reglas de idempotencia ⇒ **`/api/v2`** nuevo |
| Doble escritura | Solapamiento ≥ 90 días: los servicios aceptan ambas versiones y, si aplica, responden campo nuevo + antiguo marcado `deprecated` |
| Deprecación | `Deprecation: @<date>` (Internet-Draft HTTP API) + `Sunset: <HTTP-date>` (RFC 8594) con ≥ 180 días de aviso y `Link: rel="successor-version"` cuando exista `/api/v2` |
| Visibilidad | `GET /api/v1/version` expone `deprecations[]` con ruta, fecha `Sunset` y sucesora |
| Contratos de eventos | Complemento no REST: `event_type` + `schema_version` incremental, preferentemente aditivo; breaking estructural ⇒ nuevo `event_type` (ver ADR-0007) |
| Changelog | Toda PR que toque contratos añade entrada en `platform-contracts/CHANGELOG.md` clasificada `compatible` / `breaking` |
| SemVer | El paquete de contratos se versiona con SemVer; el mayor acompaña al major del path |

## Consecuencias

### Positivas

- El contrato es verificable en CI: imposible desplegar código que rompa clientes sin que el pipeline lo diga.
- Clientes y tipos siempre al día, generados, sin desincronización entre repos (coherente con ADR-0001).
- Integración de terceros posible sin leer el código fuente; la spec servida es documentación viva.
- Versionado explícito y sin breaking changes silenciosos, con ventanas de migración medibles.

### Negativas

- La generación restringe el estilo de los DTOs: hay que diseñar la API pensando en lo que los generadores producen.
- Mantener contract tests (productor, consumidor, consumer-driven) alarga el CI; es un coste deliberado.
- Dos ubicaciones de spec (canónica + export) exigen un gate de igualdad; sin ese gate sería una fuente de ambigüedad.
- La política de doble escritura y `Sunset` obliga a mantener código viejo ≥ 90/180 días.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **Code-first sin spec** (los clientes se escriben a mano) | Deriva garantizada entre implementación y consumidor; sin base para detección automática de breaking changes. |
| **Spec-first manual en wiki/README** | Se envejece en cuanto cambia el código; no es ejecutable ni testeable. |
| **gRPC/protobuf como contrato principal** | Añade segundo formato de contrato y tooling; la API pública y el frontend usan REST+JSON (`M-tech-stack.md` §3.1). Se mantiene descartado en Fase 1. |
| **GraphQL** | Otro modelo de autorización, caching y rate limit para una superficie que ya está definida como REST + WS (`Q-api-map.md` §6: `NO ADOPTADO`). |
| **API management comercial / portal de desarrolladores** | No se selecciona proveedor en Fase 0 (`Q-api-map.md` §6: `DECIDIR`). |

## Referencias

- `docs/phase0/Q-api-map.md` §1.1–§1.2 (prefijos y versionado), §1.8 (idempotencia), §4 (contratos y contract tests), §6 (pendientes).
- `docs/phase0/N-monorepo-structure.md` §7 (versionado de contratos), §10 (DoD estructural).
- `docs/phase0/M-tech-stack.md` §9 (contract tests), §1.
- `docs/phase0/00-decisions.md` §4 (HTTP/JSON, sin malla), §8 (envelope de eventos).
- `docs/adr/ADR-0001-monorepo.md`, `docs/adr/ADR-0007-eventos-con-outbox.md`, `docs/adr/ADR-0010-idempotencia-primero.md`.
