# C — Gap Analysis (capacidades de referencia del mercado vs. estado Fase 0)

Fecha: 2026-09-27 · Fase: 0 · Proyecto: `MonedasAR`
Advertencia: la Fase 1 aún no se ha ejecutado. Nada está `IMPLEMENTADO` en código. Estados permitidos aquí: `NO EXISTE` / `DISEÑADO` / `IMPLEMENTADO EN FASE 1` (este último solo como objetivo previsto, no como hecho). Capacidades descritas en términos genéricos del mercado; sin nombrar ni copiar a la plataforma de referencia, sin proveedores ni licencias inventados.

## 1. Trading multi-activo (spot simulado, derivados OTC, CFDs, contratos de duración)

- **Capacidades esperadas del mercado (genérico):** múltiples clases (divisas, índices, materias primas, cripto, cestas), ticket unificado market/limit/stop, TIF, SL/TP, cierre parcial, horarios y suspensiones, specs versionadas por símbolo.
- **Estado al cierre de Fase 0:** `NO EXISTE` en código; `DISEÑADO` a nivel de fases (trading en Fase 4, productos avanzados en Fase 5, gating DEMO/LIVE en `00-decisions.md` §6).
- **Brecha concreta:** sin OMS/EMS, sin motor de posiciones/margen/PnL, sin catálogo de símbolos, sin calendario de mercado. Solo existe la asignación de fases y principios (ledger, idempotencia, flags).
- **Esfuerzo relativo:** `CRITICAL`.
- **Fase prevista:** 3 (catálogo/market-data) → 4 (OMS/EMS/margin) → 5 (CFDs/riesgo-limitado).

## 2. Gráficos avanzados (charting)

- **Capacidades esperadas:** velas multi-timeframe, indicadores (MA/RSI/MACD/Bollinger), dibujos, crosshair, streaming en vivo, histórico con huecos explícitos.
- **Estado:** `NO EXISTE`; `DISEÑADO` solo como dependencia de market-data (Fase 3).
- **Brecha:** sin persistencia OHLC, sin agregador tick→vela, sin librería de indicadores propia, sin componente frontend.
- **Esfuerzo:** `HIGH`.
- **Fase prevista:** 3 (backend OHLC+WS) → 5/8 (indicadores avanzados y UX).

## 3. Wallet / Cashier (cuentas, balances, transferencias, extractos)

- **Capacidades esperadas:** vista multi-cuenta/multi-moneda, transferencias internas, historial filtrable, extractos exportables, estados DEMO/LIVE separados.
- **Estado:** `NO EXISTE`; `DISEÑADO` (wallet como proyección, ledger fuente de verdad; servicios `accounts/wallet/ledger` en Fase 2).
- **Brecha:** sin servicios accounts/wallet/ledger, sin cashier UI, sin exports. Documentos L/O/P definen principios pero no hay tablas ni APIs.
- **Esfuerzo:** `HIGH`.
- **Fase prevista:** 2.

## 4. KYC / AML (onboarding, verificación, monitoreo)

- **Capacidades esperadas:** onboarding por pasos, verificación documental/biometría, listas de sanción, risk-scoring, revisión manual, retención de evidencias.
- **Estado:** `NO EXISTE`; `DISEÑADO` como orquestación con adapters + mock (`kyc` en Fase 6).
- **Brecha:** sin flujo, sin adapter real, sin storage de evidencias, sin casos de revisión. Todo lo productivo es `REQUIERE PROVEEDOR`.
- **Esfuerzo:** `HIGH`.
- **Fase prevista:** 6 (mock/sandbox primero; live solo con proveedor + licencia).

## 5. Mercados sintéticos (índices simulados 24/7)

- **Capacidades esperadas:** series continuas con specs (volatilidad, tick mínimo), reproducibilidad/auditabilidad, etiquetado de simulación, disponibilidad 24/7.
- **Estado:** `NO EXISTE`; apenas `DISEÑADO` como idea de motor simulado en Fase 5.
- **Brecha:** sin generador, sin spec, sin feed dedicado, sin pruebas de equidad/transparencia metodológica.
- **Esfuerzo:** `HIGH`.
- **Fase prevista:** 5 (solo DEMO/simulación; cualquier oferta real es `REQUIERE LICENCIA`).

## 6. Bots / Bot builder (automatización por reglas)

- **Capacidades esperadas:** editor por bloques/reglas, variables de mercado, backtest rápido, ejecución con límites, logs y kill-switch, versionado de estrategias.
- **Estado:** `NO EXISTE`.
- **Brecha:** sin runtime de bots, sin sandbox, sin API scoped para bots, sin UI.
- **Esfuerzo:** `HIGH`.
- **Fase prevista:** 5.

## 7. Copy trading (réplica de estrategias)

- **Capacidades esperadas:** catálogo de estrategias, métricas verificables, réplica proporcional, stop-copy, transparencia de fees/riesgos.
- **Estado:** `NO EXISTE`.
- **Brecha:** sin motor de réplica, sin ranking, sin gestión de suscripciones, sin salvaguardas (límites, disclaimers).
- **Esfuerzo:** `HIGH`.
- **Fase prevista:** 5 (DEMO primero).

## 8. API pública + WebSocket (trading algorítmico e integraciones)

- **Capacidades esperadas:** REST versionado (cuentas, órdenes, posiciones, pagos, datos), WS (ticks, libro, estados), tokens scoped, cuotas, sandbox.
- **Estado:** `NO EXISTE`; `DISEÑADO` el principio API-first/OpenAPI y envelope de eventos.
- **Brecha:** sin gateway productivo, sin OpenAPI publicado, sin protocolo WS, sin sandbox.
- **Esfuerzo:** `HIGH`.
- **Fase prevista:** 1 (gateway interno) → 3 (WS datos) → 5 (API pública + sandbox).

## 9. Afiliados / IB (affiliate/partner)

- **Capacidades esperadas:** enlaces/códigos, atribución, comisiones multinivel básicas, dashboard de afiliado, anti-fraude de atribución.
- **Estado:** `NO EXISTE` (no asignado a Fase 1–7; cae en 7/8 si se prioriza).
- **Brecha:** sin modelo de atribución, sin ledger de comisiones, sin portal.
- **Esfuerzo:** `MEDIUM`.
- **Fase prevista:** 7+ (post-backoffice; no es MVP).

## 10. P2P (peer-to-peer cashier)

- **Capacidades esperadas:** publicación de ofertas, escrow, confirmaciones, disputas con SLA, reputación.
- **Estado:** `NO EXISTE`; previsto tardío (Fase 6).
- **Brecha:** sin escrow, sin motor de disputas, sin reputación, con alto riesgo fraude/KYC.
- **Esfuerzo:** `CRITICAL`.
- **Fase prevista:** 6+ (después de pagos/KYC maduros; nunca antes).

## 11. Backoffice / Admin (operaciones, soporte, finanzas, riesgo)

- **Capacidades esperadas:** vista 360 cliente, gestión KYC/pagos/disputas, ajustes con 4-ojos, flags, kill switches, auditoría total.
- **Estado:** `NO EXISTE`; `DISEÑADO` como servicio `admin` BFF en Fase 7.
- **Brecha:** sin BFF, sin colas operativas, sin flujos de aprobación.
- **Esfuerzo:** `HIGH`.
- **Fase prevista:** 7.

## 12. Reporting (operativo, financiero, regulatorio)

- **Capacidades esperadas:** extractos, PnL realizado/no realizado, comisiones/swaps, reportes regulatorios por corte, exports.
- **Estado:** `NO EXISTE`; principio de eventual consistency para reporting `DISEÑADO`.
- **Brecha:** sin jobs de reporte, sin plantillas, sin cortes auditados.
- **Esfuerzo:** `MEDIUM`.
- **Fase prevista:** 7 (operativo) → 9 (regulatorio con licencia).

## 13. Multi-idioma (i18n) + localización

- **Capacidades esperadas:** catálogos por locale, fallback, RTL, formatos ICU (moneda/fecha), contenido legal por jurisdicción.
- **Estado:** `NO EXISTE`; stack Next.js con i18n previsto (`DISEÑADO` como decisión de stack).
- **Brecha:** sin catálogos, sin pipeline de traducción, sin tests RTL/ICU.
- **Esfuerzo:** `MEDIUM`.
- **Fase prevista:** 8 (tras estabilizar flujos; legal por jurisdicción en 9).

## 14. Mobile / PWA

- **Capacidades esperadas:** app instalable, offline degradado, push, ticket/posiciones usables en pantalla pequeña, biometría opcional.
- **Estado:** `NO EXISTE`; PWA con Next.js `DISEÑADO` como decisión (Fase 1 shell).
- **Brecha:** sin shell, sin manifest/service-worker, sin push, sin flujos móviles validados.
- **Esfuerzo:** `MEDIUM`.
- **Fase prevista:** 1 (shell) → 8 (endurecimiento móvil/accesibilidad).

## 15. Responsible trading (juego responsable / trading responsable)

- **Capacidades esperadas:** autoexclusión, cooling-off, límites depósito/pérdida/sesión, test idoneidad, advertencias persistentes.
- **Estado:** `NO EXISTE`.
- **Brecha:** sin controles, sin contenido versionado, sin bloqueo efectivo cross-producto.
- **Esfuerzo:** `MEDIUM` (pero `MUST` regulatorio antes de cualquier LIVE).
- **Fase prevista:** 5 (controles DEMO) → 9 (validación legal para LIVE).

## 16. Seguridad (autenticación, autorización, fraude, custodia de secretos)

- **Capacidades esperadas:** Argon2id, JWT corto+rotación, MFA, RBAC, rate-limit, firma webhooks, threat model, secret-scan, cifrado.
- **Estado:** principios `DISEÑADOS` (`00-decisions.md` §7, ADRs); gateway/identity/audit como objetivo `IMPLEMENTADO EN FASE 1` (aún no ejecutado → hoy `NO EXISTE` en código).
- **Brecha:** toda la implementación pendiente: gateway, identity, audit, Redis, OTel, scans, threat model documentado por servicio.
- **Esfuerzo:** `CRITICAL`.
- **Fase prevista:** 1 (base) → 8 (endurecimiento) → 9 (auditoría externa).

## Resumen tabular

| Categoría | Estado Fase 0 | Brecha | Esfuerzo | Fase |
|---|---|---|---|---|
| Trading multi-activo | NO EXISTE / DISEÑADO (fases) | OMS/EMS/posiciones/margen | CRITICAL | 3–5 |
| Gráficos | NO EXISTE | OHLC/indicadores/frontend | HIGH | 3–5 |
| Wallet/Cashier | NO EXISTE / DISEÑADO (principios) | accounts/wallet/ledger/UI | HIGH | 2 |
| KYC/AML | NO EXISTE / DISEÑADO (adapter) | flujo+proveedor+storage | HIGH | 6 |
| Sintéticos | NO EXISTE | generador+spec+feed | HIGH | 5 |
| Bots | NO EXISTE | runtime+sandbox+UI | HIGH | 5 |
| Copy trading | NO EXISTE | réplica+ranking+límites | HIGH | 5 |
| API/WS | NO EXISTE / DISEÑADO (principios) | gateway/OpenAPI/WS/sandbox | HIGH | 1–5 |
| Affiliate/IB | NO EXISTE | atribución+comisiones+portal | MEDIUM | 7+ |
| P2P | NO EXISTE | escrow+disputas+reputación | CRITICAL | 6+ |
| Backoffice | NO EXISTE / DISEÑADO (BFF Fase 7) | BFF+colas+aprobaciones | HIGH | 7 |
| Reporting | NO EXISTE | jobs+plantillas+cortes | MEDIUM | 7–9 |
| Multi-idioma | NO EXISTE / DISEÑADO (stack) | catálogos+RTL+ICU | MEDIUM | 8–9 |
| Mobile/PWA | NO EXISTE / DISEÑADO (stack) | shell+SW+push+UX móvil | MEDIUM | 1–8 |
| Responsible trading | NO EXISTE | controles+contenido+bloqueo | MEDIUM | 5–9 |
| Seguridad | NO EXISTE / DISEÑADO (principios; objetivo Fase 1) | toda la implementación | CRITICAL | 1–9 |

## Qué se puede construir ya sin proveedor externo

Sin contratar ni licenciar nada: monorepo + CI/CD + gateway + identity + audit (Fase 1); schemas PostgreSQL por servicio + migraciones + outbox + Redpanda local; ledger append-only + invariantes + proyección wallet; catálogo de símbolos propio + simulador de ticks/velas etiquetado; OMS/EMS contra cotizador simulado; margen/PnL/liquidación determinista en DEMO; WS interno + frontend shell PWA; OTel/Prometheus/Grafana/Loki/Tempo; mocks de pagos/KYC/notificaciones con contratos; backtests sobre histórico propio; flags, idempotencia, auditoría y tests. Todo en `DEMO` con `live_trading=false`. Detalle ejecutable en `W-build-now.md`.

## Qué es imposible sin licencia / proveedor

- **Sin proveedor de market-data/ejecución:** precios reales, fills reales, libro real, custodia/liquidez. Solo simulación etiquetada.
- **Sin pasarela de pagos/rails fiat-cripto:** depósitos/retiros reales, conciliación bancaria, payouts. Solo mocks + diseño.
- **Sin proveedor KYC/AML + listas de sanción:** verificación real, screening, monitoreo transaccional. Solo orquestación mock.
- **Sin proveedor de comunicaciones (email/SMS/push):** notificaciones reales fuera de entorno local. Solo mock/in-app.
- **Sin licencia/autorización regulatoria por jurisdicción:** `LIVE`, apalancamiento real, oferta pública, fiscalidad, P2P con dinero real. Bloqueado por gating (ver `X-blocked-to-live.md`).
- **Sin auditoría/pen-test externo y KMS/Vault gestionado:** corte a producción con dinero real. Solo endurecimiento interno hasta entonces.
