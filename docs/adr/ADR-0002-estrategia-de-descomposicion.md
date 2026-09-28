# ADR-0002 — Estrategia de descomposición: microservicios desde el inicio con catálogo mínimo

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **Decisión del usuario:** sí (`00-decisions.md` §3)
- **ADR relacionados:** ADR-0001 (monorepo), ADR-0003 (lenguaje), ADR-0005 (datos por servicio), ADR-0007 (eventos)

## Contexto

La plataforma administra dinero real en su estado final, con prioridad de integridad financiera por encima de velocidad de desarrollo (`A-executive-summary.md` §1). Existen tres formas razonables de partir el sistema: monolito modular que se extrae "cuando duela", microservicios desde el inicio, o una descomposición intermedia por capas.

El usuario decidió microservicios desde el inicio. Eso implica un coste operativo real en una Fase 1 pequeña: 13 servicios previstos, cada uno con su cadena de migraciones, su Dockerfile, sus healthchecks, sus dashboards, su runbook y sus contract tests; comunicación por red en lugar de llamadas de función; lecturas cross-servicio solo por API o eventos (consistencia eventual en composición); debugging distribuido; despliegues independientes que exigen tolerancia a fallos en el arranque.

## Decisión

**Microservicios desde el inicio, con catálogo mínimo obligatorio y criterios formales de extracción.**

### 1. Catálogo mínimo (`00-decisions.md` §3)

| Servicio | Responsabilidad | Fase |
|---|---|---|
| `gateway` | edge: routing, validación JWT, rate limit, headers, request-id | 1 |
| `identity` | usuarios, credenciales, sesiones, MFA, RBAC, devices, login history | 1 |
| `audit` | log append-only de acciones críticas (consumidor de eventos) | 1 |
| `accounts` / `wallet` / `ledger` / `notification` | cuentas, proyección de balances, double-entry, avisos | 2 |
| `market-data` | adapters, normalización, streaming WS | 3 |
| `trading` / `risk` | OMS/EMS/posiciones/margin/PnL; límites y kill switches | 4 |
| `payments` / `kyc` | depósitos/retiros y orquestación KYC/AML vía adapters | 6 |
| `admin` | backoffice BFF | 7 |

En Fase 1 **solo se crean** `gateway`, `identity` y `audit`; el resto de directorios no se crea vacío (`N-monorepo-structure.md` §2, nota final).

### 2. Criterios formales de extracción de un nuevo servicio

Un servicio nuevo solo se aprueba si se cumplen **acumulativamente** al menos dos criterios, siendo el primero obligatorio, y siempre mediante ADR en la PR que lo añade:

1. **Límite de dominio distinto con ciclo de vida propio** (modelo de datos, reglas y vocabulario propios; no es una capa ni un módulo).
2. **Requisito de escalado independiente medible** (evidencia de carga que exige réplicas/almacenamiento propios, no intuición).
3. **Tolerancia a fallos que no puede ser global** (su indisponibilidad no debe tumbar el resto del camino crítico).
4. **Equipo/proceso independiente** (owner con roadmap y on-call propio).

**Nunca** por moda, por "escalabilidad futura" o por preferencia de framework. Un caso que no supera los criterios se resuelve como módulo dentro del servicio existente. Dentro de cada servicio la arquitectura es por capas (`api/`, `domain/`, `application/`, `infrastructure/`) de modo que una extracción futura sea barata.

### 3. Riesgo de complejidad operativa: aceptado explícitamente

Se acepta el coste de: latencia y fallos de red, timeouts/retries/circuit breakers en cada llamada, outbox y DLQ por servicio, observabilidad por servicio (métricas, trazas, logs con `service` label), consistencia eventual en lecturas que componen varios servicios, y multiplicación de pipelines de despliegue.

Se compensa con: **sin malla de servicios en Fase 1** (HTTP/JSON síncrono + Redpanda asíncrono, `00-decisions.md` §4), catálogo mínimo, `platform-kernel` deliberadamente pequeño, una sola compose local con healthchecks, arranque tolerante a fallos (ningún servicio asume orden de arranque) y los criterios de extracción estrictos de arriba.

## Consecuencias

### Positivas

- Aislamiento de fallos por bounded context y despliegues independientes desde el día 1.
- Ownership claro por servicio y por schema de datos (ver ADR-0005).
- Escalado independiente donde de verdad hace falta (rate limit del `gateway` vs I/O de `identity`).
- Fronteras de dominio forzadas por arquitectura y verificadas en CI, no por convención.
- El frontend compone vía API/BFF sin exponer consultas distribuidas.

### Negativas

- Complejidad operativa alta para un equipo pequeño: más servicios que personas en Fase 1.
- Toda lectura que cruce dominios es una llamada o un evento: más latencia y manejo de errores.
- Consistencia eventual en composiciones (vista 360 del usuario, balances proyectados) frente a consistencia fuerte dentro del servicio.
- Contratos y tests de integración multi-servicio son obligatorios desde el principio (coste de CI).
- Riesgo de extracción prematura si no se aplican los criterios: queda mitigado por el gate de ADR.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **Monolito modular con extracción "cuando duela"** | Rendimiento de iteración óptimo y menor coste operativo inicial, pero choca con la decisión explícita del usuario (`00-decisions.md` §3) y aplaza el trabajo de contratos, aislamiento de datos y observabilidad a un momento con más código que migrar. |
| **Descomposición por capas (API/batch/jobs como "servicios")** | No aporta límites de dominio reales: acopla modelos de datos y obliga a despliegues coordinados. |
| **Nano-servicios / función por caso de uso** | Multiplica la complejidad operativa sin criterios de dominio; inmanejable con el equipo actual. |
| **Malla de servicios desde Fase 1** | Añade proxies, certs y control de tráfico antes de existir tráfico; `00-decisions.md` §4 la excluye explícitamente. |

## Referencias

- `docs/phase0/00-decisions.md` §3 (catálogo y criterios), §4 (sin malla en Fase 1), §9 (alcance Fase 1).
- `docs/phase0/A-executive-summary.md` §2 (forma arquitectónica).
- `docs/phase0/N-monorepo-structure.md` §9 reglas 3, 7, 9 y 10; §10 (DoD estructural: nuevo servicio exige ADR).
- `docs/phase0/F-c4-containers.md` (contenedores y dependencias), `D-domain-map.md` (bounded contexts).
- `docs/phase0/T-roadmap.md` y `S-mvp-scope.md` (secuencia por fases).

> **Nota de numeración:** `00-decisions.md` §3 y `N-monorepo-structure.md` §9/§10 citan estos criterios de extracción como «ADR-0003». Su ubicación canónica es este ADR-0002; la numeración del citado queda obsoleta.
