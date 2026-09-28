# Feature Spec — plantilla exigible en PR de features financieras (REQ-079)

> **Estado de la plantilla:** vigente desde Fase 1 · **Origen:** `../phase0/W-build-now.md` (BUILD-006), `../phase0/B-requirements-matrix.md` (REQ-079).
> **Uso:** toda PR que toque flujos financieros (orders, payments, withdrawals, deposits, webhooks, ledger postings — `../phase0/00-decisions.md` §5) debe incluir una copia cumplimentada de esta plantilla en la descripción de la PR o en `docs/`. **Sin esta checklist completa, la revisión queda bloqueada** (REQ-079: *"falta de rollback bloquea revisión"*).

---

## 0. Identificación

| Campo | Valor |
|---|---|
| **ID** | `FEAT-XXXX` (correlativo; enlazar issue/PR) |
| **Título** | … |
| **Servicio(s)** | `gateway` / `identity` / `audit` / … (solo Fase 1; resto `PENDIENTE` según `../component-status.md`) |
| **Fase** | 1 (foundation) — cualquier fase ≥ 2 requiere además gate de `T-roadmap` |
| **Autor / revisores** | … |
| **Fecha** | `AAAA-MM-DD` |
| **Estado** | `BORRADOR` / `EN REVISIÓN` / `APROBADA` / `RECHAZADA` |

---

## 1. Alcance y no-alcance

- **Alcance (qué entra):** …
- **No-alcance explícito (qué NO entra):** … *(obligatorio: una spec sin no-alcance se devuelve)*
- **Supuestos:** …
- **Dependencias de otros servicios/fases:** … *(p. ej. requiere `accounts` Fase 2 → marcar `PENDIENTE`)*

## 2. Contratos OpenAPI afectados

> Fuente única: `packages/platform-contracts/openapi/<servicio>.yaml` (ADR-0004). Hoy el contrato versionado es `PENDIENTE` (`../component-status.md` §1); FastAPI genera `/docs` en local. No afirmar gates de CI que aún no existen.

| Ruta | Método | Cambio (`compatible` / `breaking`) | `Idempotency-Key` (`Sí`/`N/A`) | Versión (`/api/v1`, `/internal/v1`) |
|---|---|---|---|---|
| `/api/v1/…` | `POST` | … | Sí (obligatorio en mutación financiera, `../phase0/Q-api-map.md` §1.8) | … |

- [ ] Entrada añadida en `platform-contracts/CHANGELOG.md` clasificada `compatible` / `breaking` *(cuando el changelog exista; hoy `PENDIENTE`)*
- [ ] Breaking change ⇒ major nuevo (`/api/v2`) + `Deprecation`/`Sunset` + ventana ≥ 90/180 días (ADR-0004 §4). Sin esto, la PR se bloquea.

## 3. Eventos afectados

> Envelope canónico en `../phase0/P-event-catalog.md`; transporte según ADR-0007. **Realidad Fase 1:** el outbox de `identity` despacha por HTTP a `POST /internal/v1/audit-events` (`services/identity/src/identity/outbox.py`); el relay a Redpanda es `PENDIENTE` (ver `../runbooks/01-outbox-redpanda.md`).

| `event_type` | `schema_version` | Topic (`<dominio>.<entidad>.<evento>`) | Productor → consumidor | Idempotencia consumidor (`event_id`) |
|---|---|---|---|---|
| … | … | … | `identity` → `audit` | dedup por `event_id` en `services/audit/src/audit/routes.py` |

- [ ] Fila de `outbox_events` escrita **en la misma transacción** que el cambio de estado (ADR-0007 §1).
- [ ] Payload sin secretos ni PII completa (`../phase0/G-security-architecture.md` §9).

## 4. Feature flags

> Sistema propio versionado; `live_trading=false` inmutable con doble interlock (ADR-0012).

| Flag | Tipo (`boolean`/`string`/`percentage`) | Default seguro | Ámbito (`global`/jurisdicción) | `sunset`/owner |
|---|---|---|---|---|
| … | … | … | … | … |

- [ ] `mode` (`DEMO`/`LIVE`) viaja en JWT, eventos y respuestas; ningún dato simulado se presenta como real (`../phase0/00-decisions.md` §6).
- [ ] La PR **no** toca `live_trading` (cualquier intento = defecto de severidad máxima, ADR-0012 §4).

## 5. Riesgos

| Riesgo | Prob. / impacto | Mitigación | Riesgo residual |
|---|---|---|---|
| … | … | … | … |

Referencias: `../phase0/G-security-architecture.md` §10 (STRIDE), `../threat-model.md`.

## 6. Datos — clasificación y gobernanza

| Dataset/tabla | Schema (propio, ADR-0005) | Clasificación | Owner/steward | Retención | Cifrado |
|---|---|---|---|---|---|
| `identity.outbox_events` | `identity` | … | … | purga `published` + retención (`PENDIENTE` dimensionar) | `REQUIERE PROVEEDOR` en prod |

- [ ] Sin acceso cruzado a schemas ajenos (test de aislamiento, ADR-0005 §1).
- [ ] Dinero: `NUMERIC(38,18)` + `Decimal`, nunca `float` (`../phase0/00-decisions.md` §5, ADR-0006).
- [ ] Minimización de PII en logs/trazas; `ip_hash` en lugar de IP en claro salvo decisión (`../phase0/G-security-architecture.md` §9).

## 7. Plan de rollback

> Sin plan de rollback verificable la revisión queda **bloqueada** (REQ-079).

| Paso | Acción | Comando / migración `down` | Verificación |
|---|---|---|---|
| 1 | … | `…` (Alembic `downgrade`, ADR-0014) | … |
| 2 | Desactivar flag | … | … |

- [ ] Migraciones con `upgrade`/`downgrade` verdes en base efímera.
- [ ] Rollback probado o, si no pudo probarse, declarado como límite en §9.

## 8. Criterios de aceptación verificables

Cada criterio debe ser medible y enlazar evidencia (comando, test, log):

- [ ] CA-1: … *(p. ej. `uv run pytest tests/integration/test_….py` en verde)*
- [ ] CA-2: doble `POST` con misma `Idempotency-Key` = un solo efecto + `Idempotent-Replay: true` (ADR-0010).
- [ ] CA-3: evento pareado a su transacción (sin evento fantasma ni pérdida, ADR-0007).

## 9. Definition of Done

Enlazar `../templates/dod.md` cumplimentado. Sin DoD firmado no hay merge.

---

*Plantilla creada por BUILD-006 · Última revisión: 2026-09-28.*
