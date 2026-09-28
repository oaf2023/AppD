# ADR-0019 — Estrategia de consistencia CAP por subsistema

| Campo | Valor |
|---|---|
| **Estado** | Aceptada |
| **Fecha** | 2026-09-27 |
| **Alcance** | todos los subsistemas: dinero, identidad/sesiones, riesgo, market data, eventos, analytics |
| **Fuente canónica** | `docs/phase0/00-decisions.md` §5 · `docs/phase0/B-requirements-matrix.md` REQ-051 |

## Contexto

- CAP no es una elección única del sistema sino de **subsistemas y de operaciones**: ante una partición de red, cada camino debe elegir entre seguir aceptando escrituras (consistencia posterior) o rechazarlas (disponibilidad). El diseño de Fase 1 corre en compose de un nodo, pero el gate de Fase 8 exige experimentos de caos con *network partition* (`T-roadmap.md`), así que las decisiones deben estar tomadas antes.
- `00-decisions.md` §5 exige consistencia fuerte en dinero (ACID + outbox), eventual consistency **solo** en analytics/reporting, e idempotencia obligatoria en flujos financieros. `REQ-051` añade que el reporting eventual marca `as_of` y se regenera de forma idempotente.
- El riesgo R-002 (duplicados por reentregas at-least-once) y la semántica del outbox fijan que la entrega de eventos es at-least-once: no existe exactly-once extremo a extremo.
- Los SLI de market data (freshness p99 ≤ 1 s, borrador en `M-tech-stack.md` §7.1) y el patrón WS de resync snapshot+delta (`R-websocket-map.md`) implican que en cotizaciones la frescura pesa más que la entrega total.
- Sin transacciones distribuidas: cada servicio tiene su schema y su base PostgreSQL (`00-decisions.md` §3), por lo que no hay 2XA disponible ni deseable.

## Decisión

| Subsistema | Elección bajo partición | Comportamiento concreto | Trade-off aceptado |
|---|---|---|---|
| **Dinero** (`ledger`, `wallet`, `payments`) | **CP**: consistencia fuerte | Transacción ACID local + outbox en la misma transacción; si no puede confirmar contra su BD, **rechaza** la escritura (`503` + `Retry-After`, fail-closed) en lugar de aceptar degradado; sin actualizaciones optimistas de saldo | Pierde disponibilidad en la partición: depósitos/retiros se pausan; se asume porque la corrección a posteriori de dinero es peor (ADR-0011) |
| **Identidad/sesiones** (`identity`, denylist en `gateway`) | **CP en autenticación y revocación** | Login/refresh/revocación fail-closed ante fallo de `identity` o de Redis en `auth/*` (`G-security-architecture.md` §3.4); lecturas de perfil pueden degradar a caché con TTL | Un corte impide logins nuevos y no permite "dejar pasar" sesiones revocadas; preferible a sesiones zombis |
| **Riesgo pre-trade** (`risk`) | **CP: fail-closed** | Si los límites/margen no se pueden evaluar, la orden se rechaza; ningún camino de ejecución asume "sin límite = límite ilimitado" | Menor disponibilidad de trading ante fallo de `risk`; se mitiga con timeouts cortos y co-ubicación de la evaluación |
| **Market data** (`market-data`) | **AP orientado a frescura** | Se publica el último dato conocido con `timestamp`/`age`; detección de huecos y **resync snapshot+delta** al reconectar; gaps visibles, nunca rellenos con datos inventados; etiqueta `mode`/`simulated` | Puede entregar ticks incompletos o fuera de orden dentro de la ventana; el consumidor confía en la frescura y marca edad, no en la entrega total |
| **Eventos (Redpanda/outbox)** | **At-least-once + consumidor idempotente** | Reentregas y reordenaciones toleradas dentro del mismo `aggregate_id` (partición por agregado, ADR-0016); dedup por `(consumer, event_id)`; DLQ para lo no procesable | No hay exactly-once; el precio lo paga cada consumidor con su tabla de dedup |
| **Analytics/reporting** (`reporting`, dashboards) | **AP eventual** | Réplicas/consultas diferidas, informes con `as_of`, regeneración idempotente por corte (REQ-051); nunca bloquean el camino transaccional | Datos "atrasados" aceptados y etiquetados; prohibido usar una lectura eventual para decisiones de dinero |
| **Auditoría** (`audit`) | **CP en escritura de acciones críticas** | Los eventos de auditoría se originan en outbox transaccional; su consumo puede retrasarse (el log es append-only y se reconstruye desde el origen) | Retraso en la visualización del log, no pérdida: el origen transaccional es la fuente |

**Reglas transversales**

1. **Ningún servicio lee la BD de otro** (solo API + eventos): mantiene el fallo localizable y la elección CAP explícita por subsistema (`00-decisions.md` §3).
2. **Sin transacciones distribuidas**: los flujos que cruzan servicios (depósito, retiro, liquidación) usan outbox + consumo idempotente + **compensación explícita** (reversión en el ledger) cuando algo falla a mitad; nunca 2PC/XA.
3. **Fail-closed documentado por ruta**: la degradación a *fail-open* solo se admite en lecturas no financieras, queda declarada (p. ej. riesgo de rate limit en lecturas) y auditada.
4. **Tolerancia a reloj**: todo `timestamp` en UTC y con tolerancia de skew declarada; la frescura de market data se mide con la edad del dato, no con relojes sincronizados perfectamente.
5. **Validación con caos**: las elecciones de esta tabla se verifican en Fase 8 con experimentos de partición de red, pérdida de un nodo y *clock drift* antes de considerar HA real.

## Consecuencias

### Positivas

- Cada equipo conoce de antemano qué pasa cuando algo se cae: no hay debates ad-hoc durante un incidente (runbooks con la tabla anterior como base).
- El dinero nunca acepta un estado divergente: la disponibilidad se sacrifica de forma consciente y acotada, en línea con la prioridad nº1 (`A-executive-summary.md` §1).
- Market data y analytics degradan de forma útil (con marca de frescura/`as_of`) en lugar de fallar, manteniendo usable la UI.
- La elección de at-least-once + idempotencia evita el mito del exactly-once y elige un mecanismo verificable (dedup + DLQ).
- Alineamiento directo con `00-decisions.md` §5, sin reescribir decisiones ya aprobadas.

### Negativas

- Experiencia degradada en dinero durante cortes (503 en depósitos/retiros): requiere comunicación clara al usuario y reintentos con `Idempotency-Key`.
- La partición de red en Fase 1 no está probada (compose single-node): hasta Fase 8 hay confianza parcial en la tabla; documentado como riesgo.
- Los mecanismos de compensación (reversiones, reconciliaciones) añaden código y casos de prueba por cada flujo multi-servicio.
- Market data con gaps obliga al frontend a mostrar estados de "dato viejo", más complejo UI que ocultar la demora (riesgo de confusión si no se etiqueta bien).
- Mantener coherentes el reporting eventual y las vistas transaccionalmente fuertes exige doble vía de lectura (proyección vs consulta) y disciplina sobre qué consulta usa cada pantalla.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Eventual consistency también para dinero (aceptar escrituras y reconciliar después) | Genera saldos negativos, dobles gastos y correcciones contables; contradice `00-decisions.md` §5 y la prioridad de integridad financiera. |
| Transacciones distribuidas (2PC/XA) entre servicios financieros | Bloqueos distribuidos, soporte limitado en PostgreSQL+Redpanda y acoplamiento; innecesario con outbox + compensación. |
| Un modelo CAP global (todo CP o todo AP) | Todo CP deja la plataforma caída en cualquier fallo parcial; todo AP degrada el dinero; ninguno es aceptable para este dominio. |
| Sagas orquestadas como único mecanismo para todo (incluso dentro del ledger) | Complejidad innecesaria dentro de un servicio que ya es transaccional: la compensación solo se necesita entre servicios. |
| Exactly-once en el bus de eventos | Requiere coordinación transaccional entre broker y consumidores sin beneficio observable frente a idempotencia + dedup. |

## Referencias

- `docs/phase0/00-decisions.md` §3 (schemas aislados), §5 (dinero fuerte, analytics eventual, idempotencia)
- `docs/phase0/B-requirements-matrix.md` REQ-051 (reporting eventual con `as_of`)
- `docs/phase0/M-tech-stack.md` §7.1 (freshness, backlog outbox), §5 (Redpanda)
- `docs/phase0/G-security-architecture.md` §3.4 (fail-closed en `auth/*`), §7 (reintentos/timeout/cuota por par)
- `docs/phase0/P-event-catalog.md` §3.1–§3.3 (at-least-once, partición, idempotencia)
- `docs/phase0/R-websocket-map.md` (resync snapshot+delta, `sequence`); `docs/phase0/T-roadmap.md` (chaos: partición de red)
- ADR-0016 (eventos), ADR-0017 (red interna y partición), ADR-0018 (tests de idempotencia)
