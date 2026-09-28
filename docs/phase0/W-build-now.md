# W — Build Now (construible inmediatamente sin proveedor, licencia ni contrato externo)

Fecha: 2026-09-27 · Fase: 0 → objetivo 1–2 · Flag: `live_trading=false` (inmutable en este horizonte)
Regla: todo lo aquí listado es implementable con código propio + open-source + mocks. Nada requiere proveedor/licencia. Lo que sí lo requiere está en "No construible ahora" y en `X-blocked-to-live.md`. Estados: `PENDIENTE` (no iniciado, construible ya).

## 1. Foundation / Monorepo / DevOps (Fase 1)

| ID | Funcionalidad | Por qué es construible ya | Entregable esperado | Fase |
|---|---|---|---|---|
| BUILD-001 | Layout monorepo `apps/services/packages/infrastructure` + lints de frontera | Solo estructura + linters (ESLint/Ruff boundaries) | Repo con CI que falla ante import cross-dominio | 1 |
| BUILD-002 | Compose local: Postgres 17, Redis 7, Redpanda, OTel Collector | Imágenes OSS locales, sin cloud | `compose up` levanta stack + healthchecks | 1 |
| BUILD-003 | CI GitHub Actions por servicio (lint+typecheck+test+build+scan) | Runners públicos + herramientas OSS | Pipeline verde en PR con SBOM por imagen | 1 |
| BUILD-004 | Manifiestos K8s preparados + `terraform validate` de estructura | YAML/HCL estáticos, sin aplicar a cloud | `k8s/` y `terraform/` validados en CI | 1 |
| BUILD-005 | SBOM + secret-scan + umbrales CVE en CI | Herramientas OSS, sin proveedor | Bloqueo ante secreto o CVE crítica | 1 |
| BUILD-006 | Plantilla de feature spec + DoD + template ADR | Solo documentos/plantillas | `docs/templates/` exigidos en PR financieras | 1 |

## 2. Gateway / Identity / Audit / Observabilidad (Fase 1)

| ID | Funcionalidad | Por qué es construible ya | Entregable esperado | Fase |
|---|---|---|---|---|
| BUILD-007 | Gateway: routing, JWT ≤15 min, rate-limit, headers, `request-id` | FastAPI/Starlette + Redis, sin externo | Edge que rechaza JWT inválido con 401 | 1 |
| BUILD-008 | Registro/login Argon2id + refresh rotativo con detección de reuso | Libs OSS (argon2-cffi, jose), Postgres propio | Auth E2E con familia de refresh invalidada ante reuso | 1 |
| BUILD-009 | Sesiones/dispositivos/historial + revocación (denylist Redis) | Solo estado propio | API de sesiones + revocación <5 s | 1 |
| BUILD-010 | RBAC + UUIDv7 públicos + anti-enumeración login | Diseño propio, sin externo | Tests negativos por rol; sin IDs secuenciales | 1 |
| BUILD-011 | MFA TOTP opt-in + códigos de respaldo un solo uso | TOTP es estándar abierto (pyotp) | Enrolamiento + login MFA tras flag | 1 |
| BUILD-012 | Servicio audit append-only + `correlation_id`/`trace_id` | Postgres propio + outbox | Tabla inmutable; sin evento no hay acción crítica | 1 |
| BUILD-013 | Outbox + Redpanda + DLQ + reintentos con backoff | Redpanda local (API Kafka) | Publish fiable tras commit; veneno a DLQ | 1 |
| BUILD-014 | OTel + Prometheus/Grafana/Loki/Tempo + dashboards RED mínimos | Stack OSS local | Traza continua gateway→servicio→outbox | 1 |
| BUILD-015 | Feature flags versionados con `live_trading=false` + auditoría | Tabla/config propia | Flag live bloqueado; cambio auditable | 1 |
| BUILD-016 | Versionado `/v1` + OpenAPI publicado + política `Sunset` | Solo contratos propios | OpenAPI validado en CI; breaking exige major | 1 |

## 3. Dinero base: accounts / wallet / ledger (Fase 2)

| ID | Funcionalidad | Por qué es construible ya | Entregable esperado | Fase |
|---|---|---|---|---|
| BUILD-017 | Schemas `accounts/wallet/ledger` + migraciones + rollback | Postgres propio, sin externo | Migraciones up/down verdes en ephemeral | 2 |
| BUILD-018 | Ledger double-entry append-only (`NUMERIC(38,18)`, sin `float`) | Diseño en L-ledger; triggers/constraints propios | Asiento desbalanceado rechazado; sin update/delete | 2 |
| BUILD-019 | Proyección wallet + reconciliador ledger↔wallet con alerta stale | Cómputo propio | Descuadre dispara alerta + marca stale | 2 |
| BUILD-020 | Cuentas DEMO/LIVE separadas + demo auto-aprovisionada recargable | Lógica propia + flags | Registro crea DEMO; cruce DEMO/LIVE rechazado | 2 |
| BUILD-021 | Transferencias internas con idempotencia (`Idempotency-Key`) | Clave+hash propios | Doble POST = un solo movimiento | 2 |
| BUILD-022 | Historial cursor-paginado + multi-moneda con redondeo documentado | Solo código propio | Sin duplicados ante inserts concurrentes | 2 |
| BUILD-023 | Matriz de jurisdicciones + gating de producto | Tabla versionada propia | País bloqueado rechaza con código tipado | 2 |
| BUILD-024 | Suite de invariantes financieras (balance cero, no-float, outbox pareado) | Tests propios adversariales | Suite corre en CI + nightly | 2 |
| BUILD-025 | Retención/particionado/archivado con replay de saldos | Particionamiento Postgres propio | Archivado no rompe reconstrucción | 2 |

## 4. Market-data / Catálogo / Charting base (Fase 3)

| ID | Funcionalidad | Por qué es construible ya | Entregable esperado | Fase |
|---|---|---|---|---|
| BUILD-026 | Contrato `MarketDataProvider` + mock determinista (seed) etiquetado `simulated` | Generador propio, sin feed real | Mock sustituble sin tocar núcleo | 3 |
| BUILD-027 | Normalización + persistencia ticks/OHLC con huecos explícitos | Solo pipeline propio | OHLC con invariantes H/L verificadas | 3 |
| BUILD-028 | Catálogo de símbolos versionado + horarios/suspensiones | Tablas propias | Orden fuera de spec → rechazo tipado | 3 |
| BUILD-029 | WS interno: subscribe, sequence/heartbeat, snapshot+delta resync | WS propio (FastAPI/websockets) | Reconexión sin saltos verificada | 3 |
| BUILD-030 | Agregador tick→vela multi-timeframe + casos dorados | Algoritmo propio | Velas idénticas ante replay | 3 |
| BUILD-031 | Indicadores básicos propios (SMA/EMA/RSI/MACD) con tests dorados | Matemática abierta, sin vendor | Valores coinciden con fixtures | 3 |
| BUILD-032 | Benchmarks k6 de WS/market-data con datasets sintéticos | k6 OSS + datos propios | Umbrales p95 publicados en CI | 3 |

## 5. Trading DEMO: OMS / EMS simulado / Margin / Risk (Fase 4)

| ID | Funcionalidad | Por qué es construible ya | Entregable esperado | Fase |
|---|---|---|---|---|
| BUILD-033 | OMS: máquina de estados + `client_order_id` idempotente + TIF | Solo lógica propia | Transición ilegal rechazada; replay no duplica | 4 |
| BUILD-034 | Tipos market/limit/stop + SL/TP editables con resumen de riesgo | Lógica propia | Edición revalida margen + confirmación | 4 |
| BUILD-035 | EMS mock determinista + libro de fills conciliado con ledger | Simulador propio declarado | Fill huérfano → cuarentena + alerta | 4 |
| BUILD-036 | Cotizador interno solo-simulación con spread/latencia + kill-switch | Generador propio | Fuera de banda no cotiza; kill auditable | 4 |
| BUILD-037 | Margen inicial/mantenimiento + apalancamiento por matriz producto×jurisdicción | Fórmulas propias versionadas | Orden sin margen rechazada; casos dorados | 4 |
| BUILD-038 | Liquidación determinista + eventos + notificación in-app/mock | Política propia | Breach liquida según política, nunca en silencio | 4 |
| BUILD-039 | Risk pre-trade + límites + breakers + kill switches por scope | Solo reglas propias | Exceso detiene scope con evento | 4 |
| BUILD-040 | Terminal DEMO: ticket, posiciones, historial, PnL recalculado por tick | Frontend+API propios | E2E DEMO market→posición→cierre | 4 |
| BUILD-041 | Cierre parcial/total con recálculo de margen y coste base | Lógica propia | Parcial cuadra con ledger al mínimo de moneda | 4 |
| BUILD-042 | Exposición agregada/concentración + dashboard riesgo | Agregación propia + Grafana | Umbral dispara throttle + alerta | 4 |

## 6. Productos DEMO avanzados (Fase 5, sin licencia porque todo es simulado)

| ID | Funcionalidad | Por qué es construible ya | Entregable esperado | Fase |
|---|---|---|---|---|
| BUILD-043 | CFDs DEMO con PnL largo/corto + cierre parcial | Motor propio | Casos dorados + swaps desglosados | 5 |
| BUILD-044 | Swaps/financiación simulada con calendario y fórmula versionada | Calendario propio | Fórmula auditable en docs | 5 |
| BUILD-045 | Contratos riesgo-limitado DEMO (prima, barrera/duración, payoff fijo) | Spec propia | Payoff determinista por spec | 5 |
| BUILD-046 | Índices sintéticos simulados reproducibles (seed) 24/7 | Generador propio | Misma seed → misma serie | 5 |
| BUILD-047 | Bot runner sandbox DEMO + límites + kill-switch por usuario/sistema | Runtime propio aislado | Bot solo con token scoped DEMO | 5 |
| BUILD-048 | Versionado/auditoría de estrategias de bot con rollback | Tablas propias | Ejecución referencia versión inmutable | 5 |
| BUILD-049 | Copy DEMO: suscripción, réplica proporcional, stop-copy | Lógica propia | Redondeo documentado; stop cierra réplicas | 5 |
| BUILD-050 | Backtesting local determinista + métricas (retorno/DD/win-rate) | Histórico propio + libs OSS | Mismo dataset → mismo resultado | 5 |
| BUILD-051 | Responsible trading base: límites, cooling-off, autoexclusión, disclaimers | Lógica propia | Autoexclusión bloquea de inmediato | 5 |
| BUILD-052 | Sandbox API/WS DEMO con cuotas separadas y `sandbox:true` | Infra propia | Key sandbox nunca alcanza LIVE | 5 |

## 7. Notificaciones mock / Backoffice mínimo / Reporting operativo (Fases 2/7)

| ID | Funcionalidad | Por qué es construible ya | Entregable esperado | Fase |
|---|---|---|---|---|
| BUILD-053 | Adapters notificación + mock capturador + plantillas versionadas | Mock propio; proveedor real después | Mensaje visible en bandeja mock + in-app | 2 |
| BUILD-054 | Preferencias/opt-out (transaccional crítico siempre entregado) | Lógica propia | Marketing bloqueado, margen/seguridad no | 2 |
| BUILD-055 | Firma de webhooks verificada (para mocks y futuros proveedores) | HMAC estándar abierto | Firma inválida → 401 sin efecto | 2 |
| BUILD-056 | Backoffice BFF mínimo: búsqueda, vista 360 por APIs, RBAC+PII enmascarada | BFF propio, sin joins cross-servicio | Acción admin siempre auditada | 7 |
| BUILD-057 | Colas manuales: revisión de retiros/depósitos/disputas con 4-ojos | Workflow propio | Sin doble aprobación no hay payout | 7 |
| BUILD-058 | Extractos/posiciones CSV/PDF que cuadran con ledger + `as_of` | Generación propia (ReportLab/csv) | Descuadre al céntimo falla test | 7 |
| BUILD-059 | Dashboards Grafana provisionados (financiero/riesgo/técnico/DEMO-vs-LIVE) | Grafana OSS como código | Panel sin datos muestra stale, no cero falso | 7 |
| BUILD-060 | Frontend shell PWA + cashier DEMO + ticket accesible (AA base) | Next.js OSS, sin store | Lighthouse PWA + Axe sin críticas | 1 |
| BUILD-061 | i18n base (claves externalizadas, fallback, ICU fecha/moneda) | Libs OSS (next-intl/formatjs) | Locale faltante no rompe; UTC en API | 2 |
| BUILD-062 | Threat model interno v0 + runbooks de restore/outbox/WS | Documentos propios | Riesgos residuales listados antes de Fase 4 | 1 |

## No construible ahora (remite a `X-blocked-to-live.md`)

- Precios/fills/libro **reales**, custodia y liquidez → `REQUIERE PROVEEDOR` (ejecución/market-data).
- Depósitos/retiros/payouts **reales** y conciliación bancaria → `REQUIERE PROVEEDOR` (pasarelas/rails).
- Verificación documental, biometría, sanciones y monitoreo AML **reales** → `REQUIERE PROVEEDOR` (KYC/AML).
- Email/SMS/push **reales** en producción → `REQUIERE PROVEEDOR` (comunicaciones).
- Oferta `LIVE`, apalancamiento real, fiscalidad vinculante, P2P con dinero real → `REQUIERE LICENCIA` + contratos + auditoría externa.
- KMS/Vault gestionado, multi-AZ productivo, pen-test/auditoría externa → `REQUIERE PROVEEDOR` + `REQUIERE LICENCIA` para corte.
- Nada de lo anterior se simula como real: mocks etiquetados + gating `live_trading=false` hasta evidencia enlazada en el checklist de corte.
