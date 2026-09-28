# Fase 0 — Architecture & Discovery (A–Z)

Entregables de la Fase 0 del prompt maestro. Fuente de verdad: [`00-decisions.md`](00-decisions.md).

| # | Documento | Contenido |
|---|---|---|
| — | [00-decisions.md](00-decisions.md) | Decisiones canónicas del proyecto (prevalece sobre el resto) |
| A | [A-executive-summary.md](A-executive-summary.md) | Executive Architecture Summary |
| B | [B-requirements-matrix.md](B-requirements-matrix.md) | Requirements Matrix (REQ-001…) |
| C | [C-gap-analysis.md](C-gap-analysis.md) | Gap Analysis frente a capacidades de referencia |
| D | [D-domain-map.md](D-domain-map.md) | Domain Map / bounded contexts |
| E | [E-c4-context.md](E-c4-context.md) | C4 Context Diagram |
| F | [F-c4-containers.md](F-c4-containers.md) | C4 Container Diagram |
| G | [G-security-architecture.md](G-security-architecture.md) | Security Architecture |
| H | [H-trading-architecture.md](H-trading-architecture.md) | OMS, EMS, Margin, Risk, Position, Market Maker |
| I | [I-payments-architecture.md](I-payments-architecture.md) | Payments Architecture |
| J | [J-kyc-aml-architecture.md](J-kyc-aml-architecture.md) | KYC/AML + Jurisdiction Rules Engine |
| K | [K-market-data-architecture.md](K-market-data-architecture.md) | Market Data + Synthetic Market Engine |
| L | [L-ledger-architecture.md](L-ledger-architecture.md) | Ledger double-entry inmutable |
| M | [M-tech-stack.md](M-tech-stack.md) | Stack tecnológico con justificación |
| N | [N-monorepo-structure.md](N-monorepo-structure.md) | Estructura del monorepo |
| O | [O-database-strategy.md](O-database-strategy.md) | Estrategia de base de datos |
| P | [P-event-catalog.md](P-event-catalog.md) | Catálogo de eventos versionado |
| Q | [Q-api-map.md](Q-api-map.md) | Mapa API `/api/v1/` |
| R | [R-websocket-map.md](R-websocket-map.md) | Mapa WebSocket `/ws/v1` |
| S | [S-mvp-scope.md](S-mvp-scope.md) | MVP Scope |
| T | [T-roadmap.md](T-roadmap.md) | Roadmap Fase 0 → 9 con gates |
| U | [U-external-dependencies.md](U-external-dependencies.md) | Dependencias externas |
| V | [V-risk-register.md](V-risk-register.md) | Registro de riesgos (R-001…) |
| W | [W-build-now.md](W-build-now.md) | Funciones construibles ya (BUILD-001…) |
| X | [X-blocked-to-live.md](X-blocked-to-live.md) | Funciones bloqueadas hasta licencia/proveedor (X-01…) |
| Y | [Y-complexity.md](Y-complexity.md) | Complejidad por dominio (LOW→CRITICAL) |
| Z | [`../adr/`](../adr/) | ADR-0001 … ADR-0020 |

## Reglas de uso

1. Ante conflicto, prevalece `00-decisions.md` y después el ADR correspondiente.
2. Ningún documento afirma cumplimiento, licencia ni acceso a proveedores reales.
3. Clasificación de componentes: `IMPLEMENTADO` / `PARCIAL` / `MOCK` / `PENDIENTE` / `REQUIERE PROVEEDOR` / `REQUIERE LICENCIA/REGULACIÓN`.
