# ADR-0017 — Zero Trust aplicado sin malla de servicios en Fase 1

| Campo | Valor |
|---|---|
| **Estado** | Aceptada |
| **Fecha** | 2026-09-27 |
| **Alcance** | `gateway`, comunicación gateway↔servicios↔servicios, red de compose y manifests K8s |
| **Fuente canónica** | `docs/phase0/00-decisions.md` §4 (sin malla en Fase 1) · `docs/phase0/G-security-architecture.md` §7 |

## Contexto

- `00-decisions.md` §4 fija comunicación **HTTP/JSON síncrono + Redpanda asíncrono, sin malla de servicios en Fase 1**, y `M-tech-stack.md` §3.1 descarta gRPC como contrato principal. No hay cluster de Kubernetes en Fase 1: la infraestructura es docker-compose con red interna.
- El principio P4 de `G-security-architecture.md` ("no confiar en el borde") exige que, aunque el gateway valide JWT/rate limit, **cada servicio revalide** pertenencia, scope y modo; y la sección §7 define ya el objetivo: tokens de servicio con TTL ≤5 min, rutas `/internal/v1/*` bloqueadas en el edge, `x-request-id`/`x-correlation-id` por hop, mTLS como objetivo en K8s.
- Zero Trust completo (identidad por conexión, mTLS universal, políticas por par) en Fase 1 exigiría una malla (Istio/Linkerd → `DECIDIR` en `T-roadmap.md` Fase 8) o una CA propia con rotación automatizada, ambos componentes no justificados todavía.
- El modelo de amenazas reconoce el riesgo residual #4: "sin segmentación de red real hasta K8s" (`G-security-architecture.md` §10).

## Decisión

1. **Gateway como único punto de entrada externo**: solo `gateway` publica puerto; el allowlist de rutas y el bloqueo de `/internal/*` con `404` (no `403`, anti-descubrimiento) viven en el edge; los servicios no son alcanzables desde Internet. Nada habla directamente al exterior salvo los adapters con allowlist de hosts (`G-security-architecture.md` §2 SSRF).
2. **Tokens de servicio firmados y cortos**: JWT interno emitido por `identity` con TTL **≤5 min**, `iss=platform-internal`, `sub=svc:<nombre>`, `scope=svc:<nombre>`; **no** hereda scopes de usuario. Verificación de firma/expiración/`alg` en el servicio destino con JWKS. La identidad de servicio es explícita y revocable, no implícita por estar en la red.
3. **Propagación de usuario controlada**: `x-user-id`/`x-on-behalf-of` en token corto con claim `act`; **prohibido** propagar cookies o refresh tokens entre servicios; cookies jamás salen del edge.
4. **Red interna aislada**: en compose, los servicios y datos viven en red Docker interna sin puertos host publicados; en K8s (cuando exista cluster) NetworkPolicies `default-deny` + permit por par (origen, destino). El aislamiento de red es el control de transporte en Fase 1.
5. **Revalidación obligatoria en cada servicio**: el destino verifica JWT de servicio, scope, pertenencia del recurso y `mode` antes de actuar (no confía en el edge ni en el caller). Denegación por defecto.
6. **Trazabilidad e idempotencia en cada hop**: `x-request-id` y `x-correlation-id` obligatorios (coherente con ADR-0013), `Idempotency-Key` en toda mutación financiera interna, timeout corto + cuota por par (origen, destino) + circuit breaker, sin malla que los gestione.
7. **mTLS diferido a Kubernetes**: la autenticación mutua por certificado por servicio con rotación automatizada se implementa cuando haya cluster (objetivo de `G-security-architecture.md` §7, gate de Fase 8 en `T-roadmap.md`); no se crea una CA propia en Fase 1. Hasta entonces el tráfico va en claro **dentro** de la red aislada del compose (estado declarado `PARCIAL`), y se documenta que el TLS externo lo termina el edge.
8. **Qué se gana y qué se pierde** queda registrado como parte de la decisión (ver Consecuencias) y se reevalúa con el ADR de malla cuando apunte el gate de Fase 8.

## Consecuencias

### Positivas

- Zero Trust en lo esencial (identidad verificada, denegación por defecto, revalidación, edge único) con la superficie operativa mínima de Fase 1: sin sidecars, sin CA propia, sin control plane de malla.
- Un solo plano de identidad (`identity` + JWKS) y un solo punto de observabilidad y rate limit en el edge, coherentes con la Fase 1 (gateway/identity/audit).
- Coste de arranque en compose e CI bajo: los tests de seguridad (404 de `/internal`, revalidación, TTL de token) son tests de aplicación, no de infraestructura.
- Migración incremental: cuando llegue K8s, las NetworkPolicies y el mTLS añaden capas sin cambiar contratos ni código de negocio (la identidad por hop ya existe).

### Negativas

- **Sin cifrado ni autenticación mutua extremo a extremo entre servicios**: cualquier parte con acceso a la red del compose/cluster podría suplantar a un servicio mientras el TLS/mTLS no exista. Mitigación: red aislada, tokens cortos firmados (el atacante necesita clave o tiempo de vida) y revisión del gate antes de K8s.
- **Confianza residual en la red**: el aislamiento es el control primario de transporte; si un contenedor se compromete, la segmentación por par no existe hasta NetworkPolicies → riesgo de movimiento lateral detectado solo por auditoría/trazas.
- Cuotas por par, timeouts y circuit breakers se implementan a mano en cada caller (sin política central de malla): más código duplicado y posibles inconsistencias (se mitiga con helper común en `packages/`).
- El edge sigue siendo un punto único de entrada: al acertar en él se satura o se bypasea si algún servicio se expone por error (mitigación: test automatizado de que solo gateway publica puerto).
- La caducidad de 5 min obliga a renovar tokens con frecuencia: añade un mecanismo de renovación y tolerancia de reloj a considerar en los tests.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Malla de servicios (Istio/Linkerd) desde Fase 1 | Coste operativo y curva de aprendizaje altos sobre un compose con 3 servicios; tecnología `DECIDIR` pendiente de cluster real; `00-decisions.md` §4 prohíbe la malla en Fase 1. |
| mTLS con CA propia y certificados estáticos en compose | Certificados estáticos sin rotación automatizada generan deuda y fallos de expiry en local/CI; exige toolchain de CA propia sin cluster que la gestione. |
| "Confianza plena en la red interna" (sin identidad de servicio) | Contradice P2/P4: un contenedor comprometido tendría el mismo privilegio que cualquier servicio; imposible de auditar o revocar. |
| Sidecars de seguridad por contenedor sin malla | Requiere imagen, ciclo de vida y configuración por servicio con poca ganancia frente a tokens cortos + red aislada; duplicaría operaciones. |
| API key estática compartida entre servicios | Secreto compartido no revocable por identidad, aparece en logs y no permite `sub` ni auditoría por emisor. |

## Referencias

- `docs/phase0/00-decisions.md` §4 (HTTP/JSON + Redpanda, sin malla en Fase 1)
- `docs/phase0/G-security-architecture.md` §0 (P2/P4), §7 (seguridad entre servicios), §10 (riesgos residuales)
- `docs/phase0/M-tech-stack.md` §3.1 (gRPC descartado), §6 (compose y K8s preparados)
- `docs/phase0/T-roadmap.md` (gate Fase 8: network policies, mTLS `DECIDIR`)
- `docs/phase0/Q-api-map.md` §3.1 (revalidación por servicio)
- ADR-0013 (propagación de `request_id`/`correlation_id`), ADR-0019 (decisión de consistencia bajo partición de red)
