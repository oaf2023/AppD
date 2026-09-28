# ADR-0013 — Observabilidad OpenTelemetry-first con Prometheus/Grafana/Loki/Tempo

| Campo | Valor |
|---|---|
| **Estado** | Aceptada |
| **Fecha** | 2026-09-27 |
| **Alcance** | `gateway`, servicios backend, `apps/web` (lado servidor), infraestructura compose/K8s |
| **Fuente canónica** | `docs/phase0/00-decisions.md` §4 · `docs/phase0/M-tech-stack.md` §7 |

## Contexto

- `00-decisions.md` §4 fija la observabilidad en OpenTelemetry, Prometheus, Grafana, Loki y Tempo como stack de estándar abierto, sin APM SaaS con agentes propietarios (`M-tech-stack.md` §1 principio 2).
- Los gates de salida de Fase 1 (`T-roadmap.md`) exigen dashboards RED en Grafana, traza end-to-end en Tempo, logs en Loki y métricas de eventos en Redpanda: la observabilidad no es opcional en foundation.
- `G-security-architecture.md` §9 impone una política de no-logging obligatoria: sin passwords, tokens, API keys, TOTP ni PII completa en logs y trazas; atributos OTel solo por allowlist y sin body de requests en spans.
- Los SLI/SLO de `M-tech-stack.md` §7.1 están declarados como **borrador `POR VALIDAR`**: aún no hay benchmark de carga (BUILD-032) que los confirme, por lo que no pueden usarse como gate de CI.
- El riesgo de dispersión (un sistema de métricas por lenguaje, logs en formato distinto por servicio) ya fue anticipado como costo del multi-stack en `M-tech-stack.md` §4.

## Decisión

1. **OpenTelemetry como única base de telemetría**: instrumentación OTel (SDK + OTel Collector) en todos los servicios FastAPI/Starlette/SQLAlchemy/psycopg y en `apps/web` vía `instrumentation.ts`. Ningún servicio emite métricas, logs o trazas directamente a un backend: todo pasa por el Collector, que hace fan-out. Cambiar de backend no toca código de servicio.
2. **Señales y backends**: métricas → Prometheus; trazas → Tempo; logs estructurados → Loki con labels de baja cardinalidad (`service`, `env`, `mode`); dashboards y alertas → Grafana como única consola. Correlación obligatoria: `trace_id`/`request_id`/`correlation_id` comunes entre las tres señales (`00-decisions.md` §7).
3. **Contexto propagado de extremo a extremo**: el `gateway` genera/propaga `X-Request-Id` y `X-Correlation-Id`, y el contexto OTel viaja en cabeceras hacia servicios y en el envelope de eventos (`causation_id`/`correlation_id`), de modo que una traza cubre gateway → servicio → outbox → consumidor.
4. **Métricas RED por servicio** (rate, errors, duration) con histogramas de latencia por ruta, backlog del outbox (eventos sin publicar > 60 s), lag de consumidores y DLQ. Cardinalidad controlada: sin `user_id` ni IDs arbitrarios como label; esas dimensiones van a logs/trazas, no a métricas.
5. **SLI/SLO como objetivos a validar con benchmarks**: los valores de `M-tech-stack.md` §7.1 (p95 ≤ 300 ms lecturas, error rate ≤ 0,5 %, disponibilidad ≥ 99,9 %, freshness p99 ≤ 1 s, backlog outbox = 0 > 60 s) se mantienen como metas **`POR VALIDAR`**. Solo tras BUILD-032 se fijan numéricamente y, en su caso, se convierten en gates; hasta entonces se usan para dashboards y alertas exploratorias.
6. **Prohibición de PII y secretos en telemetría** (invariante, `00-decisions.md` §7): redactor de campos sensibles (`password`, `token`, `secret`, `authorization`, `cookie`, `otp`) en el logger; emails e IP hasheados por defecto; spans sin body de request ni `resource.attributes` con PII; allowlist de atributos OTel por servicio; secret-scan aplicado también a artefactos de log de CI. Los eventos en DLQ no contienen PII (`G-security-architecture.md` §9).
7. **Alertas con runbook**: ninguna alerta sin dashboard asociado y runbook en `docs/runbooks/`; burn-rate multiventana para disponibilidad/errores; alertas de integridad financiera (mismatch ledger↔proyección, DLQ activa, backlog outbox) con severidad alta.
8. **Coste y retención**: muestreo de trazas (100 % en DEMO/baja carga, muestreo configurado al crecer), retención de logs/trazas por clase, y métricas con resolución que quepa en compose local para que `docker compose up` ofrezca observabilidad completa sin infraestructura externa.

## Consecuencias

### Positivas

- Estándar abierto sin vendor lock-in: los backends (Prometheus/Grafana/Loki/Tempo) son sustituibles por cualquier compatible OTel.
- Una sola curva de observabilidad para todo el monorepo, incluida la futura convivencia de componentes en otro lenguaje si un benchmark lo justificara (ADR-0003).
- Correlación request → evento → consumidor con `request_id`/`correlation_id`, base de la auditoría de `audit` y del diagnóstico de incidentes.
- Observabilidad completa en local con compose, sin depender de credenciales de nube (regla de no-ficción).
- La política de no-logging reduce la superficie de fuga de PII/secretos y el coste de retención.

### Negativas

- Curva de configuración del OTel Collector y de las tres señales (mapeo de logs a labels, muestreo, cardinalidad) con coste de aprendizaje en Fase 1.
- Más consumo de recursos en compose (Collector + 4 backends) en una máquina local.
- Los SLO siguen sin cerrar hasta el primer benchmark: no se puede alertar con umbrales firmes desde el día 1 → riesgo de alertas ruidosas o, al contrario, de silencio.
- La allowlist de atributos limita el detalle de depuración en producción; investigar un caso concreto requiere pasar a logs/trazas con acceso restringido y auditado.
- Muestreo de trazas puede perder la traza de un incidente raro si se configura agresivamente.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| APM SaaS con agentes propietarios | Vendor lock-in, coste por nodo/dato, envío de datos de clientes a un tercero y `REQUIERE PROVEEDOR`; contradice "estándar abierto sobre propietario" (`M-tech-stack.md` §1). |
| Logs estructurados + `print`/stdlib sin métricas ni trazas | No mide latencia/errores por ruta ni sigue una petición extremo a extremo; insuficiente para los gates de Fase 1 y para auditoría correlacionada. |
| Métricas Prometheus con instrumentación manual propia (sin OTel) | Duplica trabajo por servicio y obliga a reescribir al añadir backends; OTel ya exporta a Prometheus como backend. |
| Un sistema de observabilidad por servicio (elección local de cada equipo) | Inconsistencia de labels/formatos en monorepo, dashboards no reutilizables y coste operativo multiplicado. |
| Logging con PII completa para depuración "más fácil" | Vulnera `00-decisions.md` §7 y la política de no-logging; incrementa impacto de cualquier fuga de logs. |

## Referencias

- `docs/phase0/00-decisions.md` §4 (observabilidad), §7 (no secretos/PII en registro)
- `docs/phase0/M-tech-stack.md` §7 (stack y SLI/SLO `POR VALIDAR`), §1 (estándar abierto)
- `docs/phase0/G-security-architecture.md` §9 (política de no-logging, allowlist OTel)
- `docs/phase0/T-roadmap.md` (gates G1: dashboards RED, Tempo, Loki)
- `docs/phase0/W-build-now.md` BUILD-032 (benchmark que valida los SLO)
- `docs/phase0/P-event-catalog.md` §3 (outbox, DLQ) como fuente de métricas de eventos
- ADR-0017 (propagación de identidad/trazas entre servicios)
