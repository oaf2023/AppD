# ADR-0018 — Testing de invariantes financieros como gate bloqueante de CI

| Campo | Valor |
|---|---|
| **Estado** | Aceptada |
| **Fecha** | 2026-09-27 |
| **Alcance** | `services/ledger`, `services/wallet`, `services/payments`, `services/trading`, `services/risk`, rutas de dinero en `packages/` |
| **Fuente canónica** | `docs/phase0/L-ledger-architecture.md` §8 · `docs/phase0/M-tech-stack.md` §9 · `docs/phase0/B-requirements-matrix.md` REQ-073 |

## Contexto

- La prioridad nº1 del proyecto es la integridad financiera (`A-executive-summary.md` §1); `L-ledger-architecture.md` §8 ya enumera 10 invariantes financieros verificables y fija que los tests 1–8 deben estar automatizados en CI desde la Fase 2.
- El riesgo R-002 (duplicación de ejecuciones/retiros por reintentos y reentregas at-least-once) y R-024 (corrupción de datos financieros) solo se mitigan con pruebas que fallen el merge.
- El stack de testing ya está decidido (`M-tech-stack.md` §9): pytest + pytest-asyncio (unitario), testcontainers (integración con PostgreSQL/Redis/Redpanda reales), **hypothesis** para propiedades adversariales (BUILD-024) y Playwright para E2E; los gates de CI son bloqueantes por definición en `G-security-architecture.md` §1.6.
- Un fallo de correctitud financiero no es recuperable "después": los asientos son inmutables y permanentes (ADR-0011), por lo que un bug que postea mal solo se corrige con reversión, con impacto contable y de reporte.

## Decisión

1. **Suite de invariantes financieros como job de CI bloqueante** (no *soft-fail*, sin `skip`/`xfail` permitidos en esta suite) que se ejecuta en toda PR que toque módulos de dinero. Las invariantes obligatorias son:
   - **I1 — `Σ débitos = Σ créditos`** por cada `transaction_id`, con la validación de aplicación y `ledger_assert_balanced` también como prueba de rechazo (una transacción desbalanceada debe fallar el `INSERT`).
   - **I2 — Los saldos solo cambian mediante un evento de ledger**: no existe ruta de escritura que altere un saldo; el saldo de una cuenta es siempre `Σ entries` y `wallet` coincide con el ledger después de cualquier secuencia de operaciones (property test con hypothesis: operaciones aleatorias → proyección == derivación). Verificación adicional: ninguna migración/modelo permite `UPDATE` sobre `ledger_entries`/`ledger_transactions`.
   - **I3 — Sin ejecuciones duplicadas**: replay de 100× de la misma `Idempotency-Key` con el mismo payload ⇒ 1 transacción y 1 efecto; misma clave con payload distinto ⇒ `IdempotencyConflict`; doble POST **concurrente** ⇒ 1 registro efectivo (PK en `ledger_idempotency_keys`); consumidor con evento re-entregado ⇒ 1 efecto (`consumer_processed_events`); una orden/pago no puede ejecutarse dos veces por reintento HTTP.
   - **I4 — Reconstrucción de PnL y posiciones**: replay de `OrderFilled`/`PositionClosed`/`PnlRealized`/`FeeCharged`/`SwapApplied` sobre el ledger reconstruye exactamente las posiciones y el PnL reportados (igualdad exacta con `Decimal`, no tolerancia); cierre + reversión ⇒ efecto neto cero; `outbox` emite exactamente un `LedgerPosted` por transacción committeada.
   - **I5 — Complementarias de `L-ledger-architecture.md` §8**: saldos de cuentas `asset ≥ 0`, sin mezcla de monedas salvo `type='conversion'`, `position` sin gaps, `currency` del asiento == `currency` de la cuenta.
2. **Ninguna invariante es desactivable**: la suite no admite exclusiones por entorno ni flags; un test de dinero que falle bloquea el merge (junto a lint, typecheck y secret-scan). Los skips se detectan en revisión y en un test meta que falla si aparecen `@skip`/`xfail` en los paths financieros.
3. **Cobertura mínima exigida en módulos financieros**: ≥ **90 %** de líneas y ≥ **85 %** de ramas en `services/ledger`, `services/wallet`, `services/payments`, `services/trading` (núcleo de dinero) y en los módulos `decimal`/dinero de `packages/`; ≥ 80 % de líneas como umbral global del repo. El umbral lo fija este ADR y **solo puede cambiarse por ADR nuevo** con justificación; código generado/importado puede excluirse de forma declarada y revisada. La cobertura se mide por servicio en el job de CI con path-filter (solo servicios afectados por la PR).
4. **La cobertura no sustituye a la correctitud**: el gate exige, además del porcentaje, los tests de invariantes I1–I5 (contados por identificadores o por carpeta `tests/invariants/`), de modo que no se pueda llegar al porcentaje con tests triviales de cobertura.
5. **Prohibición estructural de `float` en dinero**: regla de lint/analisis estático sobre los paths financieros (Python y TypeScript) que falla ante `float`/`number` en operaciones de monto, coherente con REQ-015 y `00-decisions.md` §5.
6. **Datos de prueba deterministas y sin producción**: fixtures propias, sin credenciales reales; las pruebas de idempotencia/concurrencia corren sobre PostgreSQL real (testcontainers) porque los invariants dependen de constraints y transacciones, no de mocks.

## Consecuencias

### Positivas

- Los defectos de dinero (desbalance, duplicados, divergencia ledger↔proyección, PnL mal recalculado) se detectan antes de merge, no en conciliación diaria o en auditoría.
- El coste de recuperación baja a cero: no llegan asientos erróneos al historial permanente (coherente con ADR-0011).
- hypothesis explora secuencias adversariales (reintentos, orden de eventos, concurrencia) que los tests de caso feliz no cubren.
- Los umbrales de cobertura blindan los módulos críticos frente a refactors con "pruebas verdes" pero sin contenido financiero.
- El gate es verificable y objetivo: sin discusión subjetiva de "creo que está probado" (regla de no-ficción).

### Negativas

- CI más lento: testcontainers + property tests + matriz de concurrencia; se mitiga con path-filter por servicio, caché de imágenes y ejecución paralela (el presupuesto de tiempo de CI se vigila en cada fase).
- Umbral alto de cobertura puede incentivar tests de relleno; se contrarresta con los tests de invariantes obligatorios y con revisión de PR.
- Falsos positivos por tests de concurrencia no deterministas → exige diseño de pruebas con semillas fijas y esperas por condición, no por tiempo.
- Mantener los invariantes sincronizados con el diseño del ledger añade trabajo por cada cambio de esquema/contrato (coste aceptado: es el contrato de correctitud).
- La suite bloquea hotfixes si un test de invariante es demasiado estricto: la excepción solo puede abrirse temporizando la invariante **por ADR y con plan de reparación**, nunca borrándola.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Umbral de cobertura único global (p. ej. 80 % en todo) | Diluye la exigencia en módulos de dinero con pantallas poco cubiertas; la integridad financiera no puede negociarse con el promedio. |
| Tests de invariantes como suite nocturna (no bloqueante) | Un defecto de dinero mergeado ya generaría asientos permanentes; la detección tardía no es recuperación. |
| Pruebas manuales/QA antes de release como control principal | No cubre concurrencia, replays ni propiedades adversariales; irreproducible y demasiado lento frente al ritmo de PRs. |
| Solo property-based sin unitarios de reglas | Difícil de diagnosticar (falta el caso concreto) y depende de la calidad de los generadores; se combina, no sustituye. |
| Mutation testing como gate desde Fase 1 | Valor alto pero coste de CPU y de mantenimiento desproporcionado aún; se evalúa tras estabilizar la suite (no bloquea ahora). |

## Estado de implementación (BUILD-024/025, 2026-09-30)

| Elemento | Implementación | Estado |
|---|---|---|
| Suite de invariantes | `tests/invariants/` (I1–I5, 20 tests, hypothesis) con perfiles `ci` (30 ejemplos, derandomizado) y `nightly` (200 ejemplos) vía `HYPOTHESIS_PROFILE` | ✅ 20/20 |
| Gates de cobertura | `tools/check_coverage.py` sobre `coverage.json`: ledger ≥90/≥85, wallet ≥85/≥85, global ≥80 líneas; ejecuta en el job `test` de CI tras pytest y en `nightly.yml` | ✅ ledger 100 %/100 %, wallet 100 %/100 %, total 94,6 % (342 tests) |
| Medición de cobertura | `coverage` con **`core = "sysmon"`** (Python 3.14): el core `greenlet` emitía eventos `return` fantasma que distorsionaban el recuento de líneas/ramas; el upgrade 3.13→3.14 + sysmon lo elimina. Ver consecuencias técnicas abajo. | ✅ |
| Lint anti-float | `tools/check_no_float.py`: AST sobre `services/*/src` y `packages/*/src` (literales, anotaciones y llamadas `float()`, con excepción de contextos temporales: timeouts/backoffs/buckets) + regex sobre `apps/` para `number`/literales en identificadores de dinero. Paso del job `quality`. Excepciones declaradas: `Quote.value`/`positive_float`/`OverviewQuote.value` en market-data (deuda de decimalización K §91). | ✅ con deuda declarada |
| Nightly | `.github/workflows/nightly.yml` (cron 04:00 UTC + dispatch manual) con perfil `nightly` + gates de cobertura | ✅ |
| Rust/Go benchmark | BUILD-032 (pendiente, sin hot spot medido) | ⏳ Fase 1+ |

### Consecuencias técnicas del upgrade de runtime (relacionado con ADR-0003)

- **Causa raíz resuelta**: con Python 3.13 y `coverage` sobre `greenlet`/`gevent`, los números de cobertura de `ledger`/`wallet` eran anómalos (eventos `return` fantasma). Con Python 3.14 y `core = "sysmon"` la medición es estable y reproducible; la suite completa pasa de 260 a 342 tests con gates reales verificables.
- **Alcance del gate de cobertura**: hoy cubre los servicios financieros existentes (`ledger`, `wallet`) + umbral global; `payments`/`trading`/`risk` (en ADR-0003) se incorporarán al gate en cuanto sus servicios existan.
- **Sin path-filter**: el gate corre en cada PR (más estricto y más simple que el path-filter hipotético del punto 3; se revisará si el tiempo de CI crece).
- **Deprecación conocida**: `platform_kernel/__init__.py` fija `asyncio.WindowsSelectorEventLoopPolicy`, deprecado y eliminado en Python 3.16; sustituir antes del próximo upgrade de runtime (afecta solo a Windows local, no a las imágenes Linux).

## Referencias

- `docs/phase0/L-ledger-architecture.md` §8 (invariantes 1–10 y cobertura mínima Fase 2)
- `docs/phase0/M-tech-stack.md` §9 (pytest, hypothesis BUILD-024, testcontainers, gates)
- `docs/phase0/B-requirements-matrix.md` REQ-073 (pirámide de testing), REQ-015 (sin `float`), REQ-081 (idempotencia)
- `docs/phase0/V-risk-register.md` R-002, R-024
- `docs/phase0/A-executive-summary.md` §1 (orden de prioridad), §6 (tests en Fase 1)
- `docs/phase0/G-security-architecture.md` §1.6 (jobs de CI bloqueantes)
- ADR-0011 (inmutabilidad que hace irrecuperable un error), ADR-0016 (idempotencia de consumidores)
