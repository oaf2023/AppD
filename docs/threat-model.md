# Threat Model interno v0 (BUILD-062)

> **Fecha:** 2026-09-28 · **Estado:** `BORRADOR v0` · **Alcance:** Fase 0 + Fase 1 (foundation: `gateway`, `identity`, `audit`).
> **Base:** `phase0/G-security-architecture.md` (§§1, 10–11), `phase0/00-decisions.md` (§§3–8), `component-status.md` (estado real verificado 2026-09-28).
> **Regla de lectura:** toda fila distingue **mitigación existente (verificada)** de **mitigación `PENDIENTE`/`REQUIERE PROVEEDOR`**. Nada de lo listado aquí es certificación (ASVS L2 es objetivo de diseño, `G-security-architecture.md` §2). BUILD-062 exige riesgos residuales listados antes de Fase 4 — este documento los declara en §5.

## 1. Activos

| # | Activo | Dónde vive (real) | Estado de protección |
|---|---|---|---|
| A1 | Dinero / ledger (fuente de verdad) | **No existe aún** — servicio `ledger` Fase 2 (`00-decisions.md` §3) | `PENDIENTE` (F2). Hoy solo rigen las reglas de diseño: `NUMERIC(38,18)`+`Decimal`, append-only (ADR-0005, ADR-0006/ADR-0011) |
| A2 | Identidad: credenciales, sesiones, refresh tokens, TOTP seeds | `platform_identity` (schemas `identity`: `users`, `sessions`, `email_outbox`, `outbox_events`, `idempotency_records`) + Redis (denylist/sesión) | `IMPLEMENTADO` (código Fase 1 verificado por suite 52 passed) — Argon2id, refresh rotativo con detección de reuso, denylist Redis |
| A3 | Audit append-only | `platform_audit` (tabla `records`, PK `event_id`; UPDATE/DELETE prohibidos por código en `services/audit/src/audit/models.py`) + ingesta `POST /internal/v1/audit-events` con dedup | `IMPLEMENTADO` (código) / verificación periódica de integridad por hash encadenado `PENDIENTE` (`G-security-architecture.md` §9) |
| A4 | Sesiones / JWT / API keys | `identity` emite; `gateway` valida (JWKS); denylist en Redis | `IMPLEMENTADO` (código) / TTL exacto de refresh y algoritmo JWT definitivo `DECIDIR` en ADR (`G-security-architecture.md` §12) |
| A5 | Secretos (pepper, `service_token_secret`, passwords de compose) | `.env` no versionado + `.env.example` con placeholders (ADR-0020); Vault/KMS `REQUIERE PROVEEDOR` | Local `PARCIAL` / producción `REQUIERE PROVEEDOR`; inventario con dueños/caducidades y rotación automática `PENDIENTE` |
| A6 | Supply chain (lockfiles, imágenes, actions) | `uv.lock`, `package-lock.json`, Dockerfiles multi-stage non-root, `.github/workflows/ci.yml` (ruff/mypy/pytest) | `PARCIAL`: SBOM por imagen, secret-scan y umbral CVE en CI **`PENDIENTE`** (`component-status.md` §6) |
| A7 | Telemetría / trazas | Logs JSON con `request_id`/`correlation_id` y redacción (`IMPLEMENTADO`); OTel Collector + Prometheus + Grafana en perfil `obs` (compose, `IMPLEMENTADO`) | Traces OTel extremo a extremo **`PENDIENTE`** (`component-status.md` §§1, 4; ADR-0013); dashboards RED/SLO y alertas `PENDIENTE` |

## 2. Trust boundaries reales (Fase 1)

```
[navegador/PWA] ──HTTPS──▶ [gateway :8080 /api/v1/] ──red Docker interna──▶ [identity :8081] [audit :8083]
        │                           │                                              │  │
        │                           │ JWT≤15min/rate-limit/headers                  │  │ outbox HTTP ─▶ POST /internal/v1/audit-events
        │                           ▼                                              ▼  ▼
        │                    [Redis :6379]                              [PostgreSQL 17 :5433: platform_identity/platform_audit/platform_gateway]
        │                    (denylist, rate limit, sesiones)
[CI GitHub Actions] ──▶ [registry] (imágenes `platform/<svc>:dev` — publicación en registry PENDIENTE)
[Redpanda :19092, perfil events] ──▶ PRESENTE en compose pero SIN productores/consumidores (outbox→audit va por HTTP)
```

Controles de frontera verificados en código: `/internal/*` bloqueado en edge; cada servicio con schema/DB propios sin acceso cruzado (`infrastructure/compose/initdb/001_databases.sql`, ADR-0005); mTLS entre servicios **`PENDIENTE`** (red Docker interna como único aislamiento local, `G-security-architecture.md` §7).

## 3. Amenazas STRIDE-lite priorizadas

> `Mitigación real` = verificada en código/config a 2026-09-28. `PENDIENTE` = diseñada pero no construida. Referencias a controles de `G-security-architecture.md` (§C) y ADRs.

| # | Escenario (STRIDE) | Mitigación real (Fase 1) | `PENDIENTE` / `REQUIERE PROVEEDOR` | Refs |
|---|---|---|---|---|
| T1 | **Account takeover** (credential stuffing, reuso de refresh, fijación de sesión) — *S,T,R,I* | Argon2id; login con backoff/lock; refresh rotativo con invalidación de familia ante reuso; denylist Redis; `session_id` nuevo por login; `login_history`; `IMPLEMENTADO` | MFA TOTP tras flag (código `IMPLEMENTADO`, enrolamiento operativo; imposición obligatoria `DECIDIR`); breach-list `PENDIENTE`; alerta de device nuevo vía notification `MOCK` | G §3; ADR-0008/0009; `G` §10 |
| T2 | **Escalada de privilegios / BOLA** — *S,T,R,I,E* | RBAC por rol en DB, filtro por `subject_id`, `404` anti-enumeración; `IMPLEMENTADO` | Tests negativos por rol en CI y RBAC fino por recurso `PENDIENTE` (F7); paso a ABAC `PENDIENTE` | G §4; `G` §10 |
| T3 | **Tampering de audit** — *T,I,D* | Append-only (`models.py` prohíbe UPDATE/DELETE) + dedup `event_id` + token de servicio ≤5 min en `/internal/v1/audit-events`; `IMPLEMENTADO` | Hash encadenado + verificación periódica de integridad `PENDIENTE`; triggers/`REVOKE` a nivel DB `PENDIENTE` | G §1.3, §9; ADR-0005/0007 |
| T4 | **Tampering de ledger / doble efecto** — *T,I,D* | Idempotencia `Idempotency-Key` + hash + respuesta almacenada (patrón ADR-0010, kernel `IMPLEMENTADO`); dinero `Decimal` sin `float` | **Ledger no existe** (Fase 2): double-entry, constraints de balance cero, reconciliador wallet↔ledger, todos `PENDIENTE` | G §1.4, §10; ADR-0005/0006/0010/0011; `00-decisions` §5 |
| T5 | **Replay / inyección de eventos** — *S,T,R* | Envelope versionado (`platform-contracts`, 9 eventos Fase 1) + dedup consumidor; outbox en misma transacción; `IMPLEMENTADO` (vía HTTP) | Relay Redpanda + ACLs de topic + DLQ `dlq.<topic>` + métrica `outbox_backlog` **`PENDIENTE`**; firma de webhooks plantilla `PENDIENTE` (F6) | G §1.4; ADR-0007/0016; `runbooks/01-outbox-redpanda.md` |
| T6 | **Abuso de API / bots / DoS de aplicación** — *S,D* | Rate limit deslizante Redis por IP/cuenta/ruta + `429`/`Retry-After` + límites de payload; `IMPLEMENTADO` (unit-tested; fixtures relajan límites en suite) | WAF / anti-DDoS perimetral `REQUIERE PROVEEDOR`; fail-closed sin Redis solo diseñado (`PENDIENTE` de test de degradación) | G §3.4, §8; `G` §10 |
| T7 | **Exposición de superficie interna** — *I* | `/internal/*` → `404` en edge; JWT de servicio `typ=service` ≤5 min; `IMPLEMENTADO` | mTLS en K8s `PENDIENTE`; NetworkPolicies `PENDIENTE` (K8s **no aplicado**, `component-status.md` §3) | G §7; ADR-0017 |
| T8 | **Fuga de secretos / PII en logs, eventos, frontend** — *I* | Redactor de campos sensibles en logs JSON; `.env` gitignored; `IMPLEMENTADO` | Secret-scan bloqueante en CI **`PENDIENTE`** (BUILD-005); SBOM **`PENDIENTE`**; cifrado de campo (TOTP seed) y en reposo productivo `REQUIERE PROVEEDOR` | G §5, §9; ADR-0020; `G` §11.1 |
| T9 | **Supply chain** (paquete/imagen/action) — *S,T,R,I,D,E* | Lockfiles + Dockerfiles pinneados + CI ruff/mypy/pytest; `IMPLEMENTADO` | Pin de actions por SHA, CVE scan con umbral, SBOM, renovación programada — todo **`PENDIENTE`** (`M-tech-stack.md` §11.1) | G §1.6–1.7; ADR-0001 |
| T10 | **Fraude en retiros / webhooks falsificados / market-data manipulada** | Fuera de Fase 1 | Servicios `payments`/`market-data`/`trading`/`risk` Fases 3–6 `PENDIENTE`; step-up MFA + maker-checker + HMAC webhooks diseñados, no construidos | G §10; `X-blocked-to-live.md` |

## 4. Controles de `G-security-architecture.md` — estado honesto

Verificados en código Fase 1: §3 (auth/sesiones/rate-limit), §4 (RBAC base), §8 (API keys con hash+expiración+allowlist), §9 (eventos + no-logging en logger). Diseñados y **`PENDIENTE`**: cabeceras §6 en gateway (código `IMPLEMENTADO` según `component-status.md` §2 — verificar con test de respuesta real antes de afirmar cobertura total), §5 (TLS/mTLS, cifrado en reposo, Vault/KMS), §11 gate LIVE completo (incl. restore probado BUILD-062, pen-test `REQUIERE PROVEEDOR`).

## 5. Riesgos residuales explícitos (revisar antes de Fase 4)

1. Sin WAF/anti-DDoS: el gateway es la única barrera de borde → `REQUIERE PROVEEDOR`.
2. Sin secret-scan/SBOM/CVE-gate en CI: un secreto o CVE puede mergearse hoy → `PENDIENTE` (BUILD-005), prioridad alta.
3. Sin traces OTel ni dashboards/alertas: detección de T5/T6 a ciegas → `PENDIENTE`.
4. Sin mTLS ni segmentación real: movimiento lateral contenido solo por red Docker local → `PENDIENTE` (K8s).
5. Secretos locales en `.env` dependen de la higiene del puesto → riesgo aceptado y documentado (ADR-0020).
6. Ledger inexistente: cualquier presión por mover valor antes de Fase 2 debe rechazarse por gate (`live_trading=false`, ADR-0012).
7. Sin pen-test ni auditoría externa → `REQUIERE PROVEEDOR` antes de cualquier LIVE (`G` §11).

---

*Threat model v0 — BUILD-062 · Revisar al cerrar Fase 1 y antes de Fase 4.*
