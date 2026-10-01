# A — Executive Architecture Summary

Fecha: 2026-09-27 · Fase 0 · Estado: `IMPLEMENTADO` (documento)
Proyecto: `MonedasAR` · Dominio: `[DOMAIN]` · Marca: `MonedasAR`

## 1. Qué es

Plataforma FinTech/Trading de derivados OTC construida desde cero, con paridad funcional de categorías con la plataforma de referencia (Deriv.com) mediante código, arquitectura, marca y componentes **legalmente independientes**. Administra dinero real en su estado final, por lo que el orden de prioridad es:

1. Integridad financiera → 2. Seguridad → 3. Cumplimiento → 4. Correctitud → 5. Auditabilidad → 6. Disponibilidad → 7. Rendimiento → 8. Escalabilidad → 9. UX → 10. Velocidad de desarrollo.

## 2. Forma arquitectónica

- **Microservicios por bounded context**, catálogo mínimo en Fase 1 (`gateway`, `identity`, `audit`) creciendo por fases según `00-decisions.md` §3.
- **Event-driven** con log duradero (Redpanda) y **transactional outbox**: el estado cambia en la misma transacción que el registro contable, los eventos se publican de forma fiable después.
- **Ledger double-entry append-only** como única fuente de verdad financiera; `wallet` es una proyección.
- **API-first**: OpenAPI como contrato único entre servicios y con clientes; WebSocket para streaming.
- **Adapters desacoplados** para pagos, KYC/AML, market data y ejecución: ningún proveedor se acopla al núcleo.
- **Feature flags** desde el día 1; `LIVE` permanentemente deshabilitado hasta licencia y proveedores reales.

## 3. Diagrama de despliegue lógico (Fase 1)

```text
[Navegador/PWA Next.js]
        │ HTTPS
        ▼
   [gateway] ── rate limit, JWT, headers, request-id, trazas OTel
   ┌────┼──────────────┐
   ▼    ▼              ▼
[identity]         [audit]      ← consumidor de eventos
   │                   ▲
   │ transaccional     │ outbox → [Redpanda] ─► consumidores
   ▼                   │
[PostgreSQL: identity] [PostgreSQL: audit]
[Redis: sesiones/rate-limit/cache]
[OTel Collector → Prometheus/Grafana/Loki/Tempo]
```

## 4. Decisiones estructurales clave (resumen; detalle en `docs/adr/`)

| Tema | Decisión | ADR |
|---|---|---|
| Monorepo único con `apps/ services/ packages/ infrastructure/` | sí | ADR-0001 |
| Microservicios desde el inicio con catálogo mínimo | sí, con criterios de extracción | ADR-0002 |
| Python 3.14 + FastAPI como lenguaje de servicio por defecto (original 3.13; upgrade BUILD-024) | sí; Rust/Go solo con benchmark | ADR-0003 |
| PostgreSQL por servicio (schema aislado), sin acceso cruzado | sí | ADR-0005 |
| Ledger append-only inmutable como fuente de verdad | sí | ADR-0005 |
| Dinero en `Decimal`/`NUMERIC`, nunca `float` | sí | ADR-0006 |
| Redpanda como log de eventos con outbox | sí | ADR-0007 |
| JWT corto + refresh rotativo con detección de reuso | sí | ADR-0008 |
| Idempotencia obligatoria en flujos financieros | sí | ADR-0010 |

## 5. Riesgo dominante

El riesgo principal no es técnico sino de **alcance**: 74 secciones de requisito. Se mitiga con fases estrictas, clasificación honesta de componentes (`IMPLEMENTADO/PARCIAL/MOCK/PENDIENTE/REQUIERE PROVEEDOR/REQUIERE LICENCIA`) y la regla de no-ficción: nunca se declara terminado lo que no está implementado y testeado.

## 6. Estado al cierre de la Fase 0

- Fase 0: documentos A–Z entregados → checkpoint de aprobación arquitectónica.
- Fase 1 (autorizada): foundation ejecutable con tests.
- Fases 2–9: pendientes de autorización explícita.
