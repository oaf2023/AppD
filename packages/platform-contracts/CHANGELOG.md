# CHANGELOG de contratos — `platform-contracts`

Regla (ADR-0004, REQ-088): este changelog registra **cada** cambio de contrato (OpenAPI y
envelope de eventos). Un cambio **breaking** (borrar/cambiar tipo/renombrar campo obligatorio)
exige bump de versión **mayor**, entrada de deprecación con política `Sunset` en la versión
anterior y guía de migración; los cambios aditivos (campos opcionales nuevos) usan bump menor.
El gate de CI (`tools/export_openapi.py --check`) impide que el spec se aleje del código.

## 0.1.1 — 2026-09-28

### Cambiado
- `info.title` de los tres specs: `[PROJECT_NAME] API Gateway` / `[PROJECT_NAME] Identity
  Service` / `[PROJECT_NAME] Audit Service` → `MonedasAR …` (rename de identidad del
  producto, `00-decisions.md` §1). Cambio de metadatos **compatible**: sin variación de
  rutas, esquemas ni `info.version`.

## 0.1.0 — 2026-09-28

### Añadido
- OpenAPI canónico inicial exportado desde la implementación (ADR-0004):
  - `openapi/gateway.yaml` — contrato de operaciones del gateway (`paths` vacío en Fase 1: el
    gateway es proxy transparente con `include_in_schema=False`; la superficie pública la
    componen los specs de los servicios dueños).
  - `openapi/identity.yaml` — registro/login/refresh/sesiones/MFA/forgot-reset (v1).
  - `openapi/audit.yaml` — ingesta interna de eventos + consulta con RBAC (v1).
- Envelope de eventos Fase 1 (`events.py`): 9 tipos `EVENT_TYPES`, `EventEnvelope`,
  `topic_for_event()` (`<dominio>.<agregado>.<evento>`, p. ej. `identity.user.registered`),
  `dlq_topic()` (`dlq.<topic>`) y `PHASE1_TOPICS`.
- Cabeceras internas (`headers.py`), roles (`roles.py`) y esquemas de audit (`audit.py`).
