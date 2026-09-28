# ADR-0012 — Feature flags desde Fase 1 y separación técnica DEMO/LIVE

| Campo | Valor |
|---|---|
| **Estado** | Aceptada |
| **Fecha** | 2026-09-27 |
| **Alcance** | plataforma completa: `gateway`, servicios, `apps/web`, CI/CD |
| **Fuente canónica** | `docs/phase0/00-decisions.md` §6 · `docs/phase0/W-build-now.md` BUILD-015 · `docs/phase0/X-blocked-to-live.md` X-01 |

## Contexto

- `00-decisions.md` §6 exige dos modos explícitos (`DEMO`/`LIVE`) y que `LIVE` sea código **deshabilitado por defecto** mediante `feature_flag live_trading = false`, bloqueado hasta licencia, proveedor de ejecución, contratos y aprobación legal.
- Requisitos vinculantes: REQ-083 (flags versionados desde el día 1, `live_trading=false` inmutable), REQ-009 (bloqueo de LIVE sin licencia), REQ-124 (flags por entorno/usuario/cohorte con auditoría), REQ-126 (dashboard con gating visible), REQ-065/§jurisdicciones (flags por jurisdicción, R-026).
- El riesgo R-017 (confusión DEMO/LIVE) y R-007 (operar sin licencia) exigen doble interlock: flag + gate de fase; ningún cambio de calendario activa LIVE (`X-blocked-to-live.md` §2).
- Hoy no existe implementación de flags: BUILD-015 los declara `PENDIENTE` en Fase 1 y la administración completa (BFF `admin`) llega en Fase 7 (`D-domain-map.md` #11, `Q-api-map.md` `PUT /api/v1/admin/feature-flags/{flag_key}`).
- Un proveedor/SDK externo de feature flags sería un proveedor nuevo sin evaluación: aplica la regla de no-ficción (`00-decisions.md` §10).

## Decisión

1. **Sistema de flags propio, versionado en el monorepo** (sin SDK externo): la definición canónica de cada flag vive en un archivo versionado por servicio (`key`, tipo, default, owner, fase de retirada), con tipos validados. El valor efectivo se resuelve así: `default en repo → override por entorno (config/env) → override persistente en tabla feature_flags`. Un error de resolución cae al default seguro.
2. **Cuatro ámbitos (scopes) con precedencia determinista**, de más específico a menos: `cuenta > segmento > jurisdicción > global`. La evaluación es una función pura, compartida desde `packages/` (mismo código en gateway, servicios y frontend), con la jurisdicción tomada de la cuenta/sesión y el segmento del perfil (`accounts`, Fase 2). En Fase 1 solo existen `global` y `jurisdicción`; `segmento` y `cuenta` quedan tipados y probados con fixtures hasta que `accounts` esté operativo.
3. **Tipos de flag**: `boolean` (gate de funcionalidad), `string` (variante/cohorte), `percentage` (rollout determinista por hash estable de `subject_id`, sin PU experimentation). Cada flag tiene owner, descripción y `sunset` (fecha de retirada); el inventario se revisa en cada gate de fase para evitar deuda de código muerto.
4. **`live_trading` como flag especial inmutable**: nace en `false` en todos los entornos, **no puede** activarse vía API ni por operador; su activación solo ocurre por proceso documentado de gate (licencia, proveedores, contratos, aprobación legal) con evidencia en `X-blocked-to-live.md`. Doble interlock: flag + gate de fase; test en CI (`REQ-009`) que falla si el valor por defecto deja de ser `false` o si el gating puede saltarse. Cualquier intento es defecto de severidad máxima.
5. **Separación DEMO/LIVE como atributo de datos, no solo de configuración**: `mode` viaja en el JWT (`claim mode`), en todo evento (`payload.mode`), en toda respuesta de API y en todo payload WS (`R-websocket-map.md`), con banner visible en UI. Ningún dato simulado se presenta como real; las claves sandbox jamás alcanzan rutas LIVE (`G-security-architecture.md` §8.2). Las bases/schemas se separan por entorno (`V-risk-register.md` R-017).
6. **Auditoría de cambios**: toda mutación de flag emite el evento `flag.changed` (actor, clave, valor previo→nuevo, motivo) hacia `audit` por outbox (`G-security-architecture.md` §9 #14). Desde Fase 7 los cambios exigen `admin` + maker-checker; `live_trading` queda fuera del alcance de la API de administración.
7. **Evaluación en caliente con caché corta**: resolución con caché en Redis (TTL del orden de 60 s) + invalidación explícita tras un cambio; en flags de seguridad (p. ej. `live_trading`, rate limit fail-closed) se aplica **fail-closed**: si la fuente no responde, se asume el valor restrictivo por defecto.
8. **Cobertura de código muerto**: el CI ejecuta los tests de cada servicio con ambos valores de sus boolean flags (matriz mínima), de modo que deshabilitar un flag nunca oculta código sin probar.

## Consecuencias

### Positivas

- `LIVE` es técnicamente imposible de activar por accidente o por presión de calendario: doble interlock + test de CI + auditoría.
- Despliegues independientes de releases: se puede desplegar código LIVE deshabilitado y activarlo por gate, sin re-despliegue.
- Rollout progresivo y reversión instantánea por flag (circuit breaker de producto) sin rollback de build.
- Granularidad suficiente para requisitos regulatorios por jurisdicción (R-026) y para cohortes de usuarios sin feature branches.
- Trazabilidad completa de cambios de configuración vía `flag.changed` en `audit`.

### Negativas

- Superficie extra en Fase 1: tablas/config, API de lectura (`GET /api/v1/feature-flags`), caché y tests de ambos valores.
- Riesgo de *flag sprawl*: cada flag es deuda de mantenimiento; se mitiga con owner obligatorio y `sunset` revisado en cada gate.
- Dos valores probados multiplican la matriz de CI (coste de tiempo); se acota a boolean flags de servicio y se deja `percentage` fuera de la matriz completa.
- La precedencia de ámbitos añade una fuente de verdad más a considerar al depurar "¿por qué ve el usuario X esto?" → se expone el origen del valor en logs de debug y en el dashboard admin (F7).
- El modo DEMO como requisito de etiquetado obligatorio impone un campo `mode` en todos los contratos (API, eventos, WS): fricción de diseño aceptada.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Variables de entorno por despliegue (sin flags runtime) | Exige re-despliegue para activar/desactivar, sin targeting por jurisdicción/cuenta ni reversión rápida; insuficiente para R-026 y REQ-124. |
| SDK/SaaS externo de feature flags | `REQUIERE PROVEEDOR` sin evaluación; añade terceros al camino de autenticación y de decisión de modo LIVE, contra la regla de no-ficción. |
| Feature branching (flag = rama git) | Duplica código no integrado, rompe CI continuo y hace imposible el despliegue de LIVE deshabilitado en `main`. |
| Solo `DEMO` hasta Fase 9 y código LIVE fuera del repo | El código LIVE debe existir deshabilitado para probarlo y auditarse antes del gate; mantenerlo fuera retrasaría la evidencia de readiness. |
| Flags por usuario sin ámbito de jurisdicción | No cubre requisitos regulatorios por jurisdicción (R-026, REQ-009) que son condición de activación. |

## Referencias

- `docs/phase0/00-decisions.md` §6 (DEMO/LIVE), §10 (no-ficción)
- `docs/phase0/W-build-now.md` BUILD-015; `docs/phase0/X-blocked-to-live.md` X-01
- `docs/phase0/B-requirements-matrix.md` REQ-009, REQ-083, REQ-124, REQ-126
- `docs/phase0/Q-api-map.md` (`GET /api/v1/feature-flags`, `PUT /api/v1/admin/feature-flags/{flag_key}`, `403 MODE_DISABLED`)
- `docs/phase0/G-security-architecture.md` §8.2, §9 #14, §11 (gate LIVE)
- `docs/phase0/H-trading-architecture.md` (modos, inyección de adapter), `R-websocket-map.md` (`mode` en payloads)
- `docs/phase0/V-risk-register.md` R-007, R-017, R-026; `docs/phase0/D-domain-map.md` #11
