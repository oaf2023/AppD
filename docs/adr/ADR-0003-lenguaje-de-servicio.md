# ADR-0003 — Lenguaje de servicio: Python 3.14/FastAPI por defecto; sin Rust/Go en Fase 1 salvo benchmark

- **Estado:** Aceptada
- **Fecha:** 2026-09-27 (runtime actualizado de 3.13 a 3.14 en BUILD-024, ver ADR-0018)
- **ADR relacionados:** ADR-0002 (descomposición), ADR-0004 (contratos), ADR-0006 (representación del dinero), ADR-0018 (testing de invariantes y gates)

## Contexto

El stack de Fase 1 (`00-decisions.md` §4) fija **Python 3.14 + FastAPI + Pydantic v2 + SQLAlchemy 2 async** como backend (versionado de 3.13 a 3.14 en BUILD-024: sysmon reemplaza a greenlet como `coverage` core y elimina eventos `return` fantasma en la medición de cobertura, ver ADR-0018). La latencia crítica de un OTC (aceptación de orden, ingest y difusión de ticks) es el punto donde normalmente se invoca Rust o Go. Introducir un segundo lenguaje tiene coste concreto: toolchain e imágenes adicionales, pipeline de CI duplicado, contratos FFI/IPC entre lenguajes, dos curvas de observabilidad por runtime, duplicidad de controles de seguridad y **dos formas de modelar dinero** (`Decimal` vs `f64`), justo donde `00-decisions.md` §5 exige una sola vía verificable.

Además hoy no hay ningún hot spot medido: la Fase 1 es I/O-bound (PostgreSQL/Redis/Redpanda), y los SLO de latencia son todavía un borrador `POR VALIDAR` (`M-tech-stack.md` §7.1). Optimizar sin perfil es especulación.

## Decisión

1. **Python 3.14 es el lenguaje por defecto de todos los servicios de Fase 1.** FastAPI (async sobre Starlette), Pydantic v2 en modo estricto para payloads financieros, SQLAlchemy 2 async + Alembic, `asyncio.TaskGroup` para consumidores y relés.
2. **Prohibido introducir Rust o Go en Fase 1** salvo que un **benchmark obligatorio** (definido abajo) demuestre incumplimiento del SLO con la implementación Python ya optimizada.
3. Si se aprueba, la migración es **de componente**: el módulo se aísla tras su API versionada existente (mismo OpenAPI, mismos eventos), convive con Python dentro del mismo servicio y **no** se migra el servicio completo.

### Benchmark obligatorio (condiciones cumulativas)

| # | Condición |
|---|---|
| 1 | Existe un componente identificado como cuello de botella **por perfilado** (OTel spans, `cProfile`, métricas por endpoint), no por intuición. |
| 2 | La implementación Python ya aplicó las optimizaciones guiadas por perfil: caché, batching/pipelining, reducir allocations, `pydantic-core`, numpy/vectorización, evitar N+1, compaction de payloads. |
| 3 | Bajo carga sintética realista (k6/locust en `tests/load/`, datasets propios, concurrencia del pico proyectado por fase) el componente **incumple el SLO candidato** o excede el umbral de coste aceptado de CPU. |
| 4 | El resultado se reproduce en **2 ejecuciones independientes** y se archiva como artefacto en este ADR: informe + script de carga + perfil. |
| 5 | El ADR de migración propone alcance mínimo (solo ese componente), estrategia de contrato (idéntica para consumidores), despliegue y coste operativo estimado. |

### Métricas medibles del benchmark

| Métrica | Definición | Umbral |
|---|---|---|
| **p95 de aceptación de orden** | Desde la recepción del `POST /api/v1/orders` en el gateway hasta la respuesta con la orden persistida (incluye validación de riesgo y escritura) | SLO candidato a fijar con el primer benchmark de carga (`W-build-now.md` BUILD-032); hoy `POR VALIDAR` |
| **Throughput de ticks** | Ticks ingeridos, normalizados y publicados por segundo y por réplica de `market-data` en pico proyectado de Fase 3 | `POR VALIDAR` con BUILD-032 |
| **Uso de CPU por réplica** | % CPU sostenido y memoria RSS en el pico, por servicio | Umbral de coste aceptado por réplica, fijado en el mismo benchmark |
| **Error rate** | 5xx + timeouts / total bajo carga | Coherente con el SLO de `M-tech-stack.md` §7.1 (≤ 0,5 % mensual) |

Los umbrales numéricos concretos **se fijan con el primer benchmark de Fase 1** y se documentan aquí; no se optimiza contra un número no medido.

## Consecuencias

### Positivas

- Un solo lenguaje de servicio: una curva de operación, un pipeline de CI, un conjunto de linters.
- Coherencia total en dinero: `decimal.Decimal` en todo el camino financiero, sin conversión a `f64` en un segundo runtime.
- Ecosistema cuantitativo/data disponible para `market-data`, `trading` y `risk` sin puentes FFI.
- FastAPI genera OpenAPI desde los modelos: contrato único sin duplicación (ADR-0004).
- Se evita pagar el coste de un segundo lenguaje sin evidencia.

### Negativas

- Python tiene techo en cómputo puro (GIL): si el benchmark lo demuestra, habrá que rehacer parte del trabajo en otro lenguaje.
- Riesgo de que el benchmark se posponga: mitigado haciéndolo obligatorio en BUILD-032 antes de fijar SLO.
- Riesgo de bloqueos accidentales del event loop en código async: mitigado con mypy estricto, revisión de `await` en hot path y tests de concurrencia (`M-tech-stack.md` §11).
- Si algún día se aprueba Rust/Go, hay que mantener dos toolchains y dos instrumentaciones OTel.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **Rust/Go desde el inicio** | Sin hot spot medido ni SLO fijado: coste de segundo lenguaje y pérdida del ecosistema cuantitativo sin beneficio demostrable. Candidatos únicos a reintroducir vía benchmark. |
| **Node.js / NestJS** | Añade otro runtime con otro manejo de errores y de `Decimal` para dinero; el stack decidido es Python (`00-decisions.md` §4). |
| **Java / Spring** | Overhead JVM en muchos contenedores pequeños y toolchain más pesado sin ventaja que compense en Fase 1. |
| **Django / DRF** | Orientado a monolito sync; el backoffice es un BFF propio en Fase 7; opiniones no justificadas para servicios finos. |
| **Python + extensiones C/Cython en el hot path** | Viable como optimización intermedia dentro del criterio 2 del benchmark; no sustituye al perfilado. |

## Referencias

- `docs/phase0/00-decisions.md` §4 (stack definitivo, "Sin Rust/Go en Fase 1").
- `docs/phase0/M-tech-stack.md` §3 (backend), §4 (benchmark obligatorio y condiciones), §7.1 (SLO candidatos), §9 (k6 como base del benchmark).
- `docs/phase0/W-build-now.md` BUILD-032 (primer benchmark de carga).
- `docs/adr/ADR-0004-api-first-y-contratos.md`, `docs/adr/ADR-0006-representacion-del-dinero.md`.
