# CHANGELOG de contratos — `platform-contracts`

Regla (ADR-0004, REQ-088): este changelog registra **cada** cambio de contrato (OpenAPI y
envelope de eventos). Un cambio **breaking** (borrar/cambiar tipo/renombrar campo obligatorio)
exige bump de versión **mayor**, entrada de deprecación con política `Sunset` en la versión
anterior y guía de migración; los cambios aditivos (campos opcionales nuevos) usan bump menor.
El gate de CI (`tools/export_openapi.py --check`) impide que el spec se aleje del código.

## 0.5.0 — 2026-09-30

### Añadido
- `DEMO_BALANCE_RESET = "DemoBalanceReset"` (catálogo P #17) y `ACCOUNT_CLOSED =
  "AccountClosed"` (catálogo P #39, nuevo), ambos con agregado `TradingAccount` y
  `schema_version = 1`, publicados por `accounts` en su outbox (recarga y cierre de
  cuenta demo, F2.3). `PHASE2_TOPICS` pasa de 3 a 5: `accounts.trading_account.demo_balance_reset`
  y `accounts.trading_account.account_closed`.
- `LedgerPosted` (#38) incorpora en cada entrada de `entries[]` los campos opcionales
  `owner_id` y `owner_type` (aditivo; `schema_version` se mantiene en 1): la proyección
  `wallet` necesita el propietario de cada asiento para aplicar el delta sin resolver
  `account_id -> owner` en tiempo real.

## 0.4.0 — 2026-09-30

### Añadido
- `ACCOUNT_CREATED = "AccountCreated"` (catálogo P #12) y `DEMO_ACCOUNT_CREATED =
  "DemoAccountCreated"` (catálogo P #16), ambos con agregado `TradingAccount` y
  `schema_version = 1`, publicados por el nuevo servicio `accounts` en su outbox.
- `EVENT_TYPES_PHASE2` (dict de versiones de los eventos Fase 2) y
  `PHASE2_TOPICS` ampliado: `accounts.trading_account.account_created`,
  `accounts.trading_account.demo_account_created`. `EVENT_TYPES`/`PHASE1_TOPICS`
  (Fase 1, 9 tipos) quedan intactos.

## 0.3.0 — 2026-09-29

### Añadido
- OpenAPI canónico del nuevo servicio `ledger` (`openapi/ledger.yaml` y el export
  `services/ledger/openapi.yaml`, generados con `tools/export_openapi.py`): la única
  vía de escritura del libro mayor, `POST /internal/v1/postings` (201, `Idempotency-Key`
  obligatorio), `GET /internal/v1/postings/{id}` y health/ready. Spec **aditivo**: no
  modifica rutas ni esquemas de gateway/identity/audit/market-data.
- `LEDGER_POSTED = "LedgerPosted"` (`events.py`, catálogo P #38) con agregado
  `LedgerTransaction` y `PHASE2_TOPICS = ("ledger.ledger_transaction.ledger_posted",)`.
  `EVENT_TYPES`/`PHASE1_TOPICS` (Fase 1, 9 tipos) quedan intactos.

## 0.2.0 — 2026-09-28

### Añadido
- Contrato de la vista de mercados (`market_data.py`): `MarketOverview`,
  `MarketClassOverview` y `OverviewQuote` para `GET /api/v1/market-data/overview`
  (Forex/Crypto informativos de proveedores keyless; ver `docs/API_INTEGRATIONS.md`).
  `OverviewQuote.simulated` es `Literal[false]` estructural: G3 (X-07) sigue bloqueado.
- OpenAPI canónico del nuevo servicio `market-data` (`openapi/market-data.yaml` exportado
  desde `services/market-data`). Spec nuevo **aditivo**: no modifica rutas ni esquemas
  de gateway/identity/audit.

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
