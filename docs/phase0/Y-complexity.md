# Y — Estimación de complejidad por dominio

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Escala: **LOW / MEDIUM / HIGH / CRITICAL**. No se estiman tiempos: no hay información suficiente para una estimación honesta de esfuerzo (equipo, alcance definitivo, jurisdicción objetivo). La complejidad se estima por: número de invariantes financieros, impacto regulatorio, dependencias externas, concurrencia exigida y coste de un fallo.

## 1. Matriz por dominio

| ID | Dominio | Complejidad | Justificación (factores dominantes) | Fase prevista |
|---|---|---|---|---|
| CX-01 | Ledger (double-entry, inmutable) | **CRITICAL** | Invariantes financieros estrictos, idempotencia, concurrencia, reversión sin borrado, reconciliación. Un fallo es pérdida de dinero. | 2 |
| CX-02 | Payments (depósitos/retiros) | **CRITICAL** | Proveedores externos, webhooks firmados, AML, fraude, maker-checker, estados complejos, fondos reales. | 6 |
| CX-03 | Trading engine (OMS/EMS) | **CRITICAL** | Concurrencia extrema, exactamente-una-ejecución, matching, orden de eventos, reconciliación con ledger. | 4 |
| CX-04 | Risk / Margin / Liquidation | **CRITICAL** | Cálculos en tiempo real sobre posiciones vivas; error = exposición no controlada. | 4 |
| CX-05 | KYC/AML + Jurisdicciones | **HIGH** | Proveedores externos, reglas regulatorias por país, revisión manual, PII sensible. | 6 |
| CX-06 | Identity/Auth (sesiones, MFA, RBAC) | **HIGH** | Superficie de ataque principal, account takeover, token rotation, rate limiting. | 1 |
| CX-07 | Market data (adapters, streaming) | **HIGH** | Normalización multi-proveedor, frescura, detección de huecos, escala de conexiones WS. | 3 |
| CX-08 | Sintéticos (Synthetic Market Engine) | **HIGH** | Algoritmos originales auditables, reproducibilidad por seed, tests estadísticos, percepción de imparcialidad del precio. | 3 |
| CX-09 | Gateway (edge, rate limit, auth) | **HIGH** | Punto único de entrada, DoS, cabeceras, propagación de trazas, disponibilidad. | 1 |
| CX-10 | P2P marketplace + escrow | **HIGH** | Fondos retenidos en custodia, disputas, fraude, AML. | 6+ |
| CX-11 | Copy trading | **HIGH** | Reparto de asignaciones, riesgo agregado, reclamaciones de rentabilidad. | 5+ |
| CX-12 | Bots / strategy engine / backtesting | **HIGH** | AST, validación, look-ahead bias, ejecución concurrente sobre cuentas. | 5 |
| CX-13 | API pública (keys, scopes, quotas) | **MEDIUM** | Patrón conocido; cuidado con enumeración, abuso y rotación de secretos. | 1 |
| CX-14 | Wallet (vista de saldos, transferencias) | **MEDIUM** | Relativamente simple si el ledger es la verdad; riesgo si se duplica lógica. | 2 |
| CX-15 | Reporting/Statements/Export | **MEDIUM** | Volumen y formatos; complejidad media si consulta proyecciones ya verificadas. | 7 |
| CX-16 | Audit / observabilidad | **MEDIUM** | Infra conocida; exigencia de append-only y no-PII en telemetría. | 1 |
| CX-17 | Backoffice / admin | **MEDIUM** | CRUD extenso con RBAC y maker-checker; alto volumen de pantallas, baja innovación. | 7 |
| CX-18 | CRM / soporte / tickets | **MEDIUM** | Integraciones y SLA; poco riesgo financiero directo. | 7 |
| CX-19 | Notificaciones (email/SMS/push) | **LOW** | Adapter + cola + plantillas; adaptadores externos pero patrón estándar. | 2 |
| CX-20 | i18n / accesibilidad / SEO público | **LOW** | Trabajo amplio pero de riesgo bajo; se aborda desde Fase 1. | 1 |
| CX-21 | Feature flags / configuración | **LOW** | Mecánica simple con alto valor de control. | 1 |
| CX-22 | Affiliate/IB | **MEDIUM** | Cálculos de comisión, atribución, fraude de referidos. | 7+ |
| CX-23 | Analytics de producto | **LOW** | Eventos agregados, sin PII innecesaria. | 7 |
| CX-24 | Infra/DR/K8s multi-región | **HIGH** | Operación en fallo, pruebas de restauración, coste de complejidad. | 8 |

## 2. Lectura de la escala

- **CRITICAL**: un defecto puede producir pérdida financiera, incumplimiento o fraude. Exige tests de invariantes bloqueantes, revisión por pares obligatoria, audit trail completo y gate de seguridad.
- **HIGH**: un defecto afecta a seguridad, disponibilidad o correctitud material, pero existe contención manual.
- **MEDIUM**: defectos con impacto acotado y reversibles.
- **LOW**: impacto limitado, fácil de corregir en caliente.

## 3. Reglas de prioridad derivadas

1. Los dominios CRITICAL no se adelantan a su fase ni se implementan "rápido para demostrar": cada uno tiene sus invariantes y tests antes de integrarse.
2. Un dominio LOW/ MEDIUM jamás bloquea la disponibilidad de uno CRITICAL ya testeado (el orden de fases prioriza integridad financiera).
3. La complejidad se re-evalúa en cada gate de fase (`T-roadmap.md`); si crece, se replanifica antes de implementar, no después.

## 4. Lo que NO se estima

Tiempos, costes, headcount y fechas: **NO DETERMINADO**. Requiere definición de equipo, jurisdicción objetivo, proveedores y alcance definitivo del MVP comercial.
