# ADR-0011 — Ledger double-entry append-only como única fuente de verdad financiera

| Campo | Valor |
|---|---|
| **Estado** | Aceptada |
| **Fecha** | 2026-09-27 |
| **Alcance** | `services/ledger` (Fase 2), `services/wallet`, `services/payments`, `services/trading` |
| **Fuente canónica** | `docs/phase0/00-decisions.md` §5 · `docs/phase0/L-ledger-architecture.md` |

## Contexto

- La plataforma administra dinero real en su estado final; la prioridad nº1 es la integridad financiera (`A-executive-summary.md` §1), por encima de disponibilidad y rendimiento.
- `00-decisions.md` §5 establece que el **Ledger** es la única fuente de verdad de saldos, que `wallet` es solo una proyección verificable y que la consistencia en dinero es fuerte (ACID + outbox).
- Un modelo de saldos mutables (`UPDATE accounts.balance` + log de auditoría separado) no permite reconstruir el histórico, oculta correcciones y expone condiciones de carrera entre lecturas de saldo y escrituras concurrentes.
- Los riesgos directos ya identificados son R-002 (duplicación de movimientos), R-024 (migraciones destructivas sobre datos financieros) y el threat de *tampering* de ledger (`G-security-architecture.md` §10): modificar saldos o asientos sin rastro.
- El diseño detallado (esquema, SQL, índices, flujos de asientos, invariantes) ya está especificado en `L-ledger-architecture.md`; este ADR fija la decisión estructural que lo gobierna.

## Decisión

1. **Double-entry obligatorio**: toda transacción financiera genera ≥2 asientos en `ledger_entries` con `Σ débitos = Σ créditos` por `transaction_id`. Se valida en aplicación antes del `COMMIT` y como defensa en profundidad con la función `ledger_assert_balanced(tx_id)` (plpgsql) más `CHECK (amount > 0)` y `direction IN ('D','C')`.
2. **Append-only real, no solo por convención**: `INSERT` es la única operación permitida sobre `ledger_entries` y `ledger_transactions`. Se garantiza con `REVOKE UPDATE, DELETE` sobre las tablas, `ON DELETE RESTRICT` en las foreign keys, regla de lint/revisión que prohíbe `UPDATE`/`DELETE` en esos paths y trigger anti-modificación como el previsto para `audit`.
3. **Balances como proyecciones verificables**: el saldo siempre se deriva del ledger (`ledger_account_balances` = Σ de asientos). `wallet` y cualquier vista de saldo son proyecciones que se contrastan diariamente contra el ledger con el job `balance_integrity_verification`, que persiste `ledger_balance_snapshots` (`ledger_balance` vs `balance`, `matched`). Una discrepancia genera alerta; **nunca** se corrige el saldo escribiendo sobre el ledger ni sobre la proyección "para cuadrar".
4. **Corrección solo por transacción de reversión enlaceada**: un error se revierte con una transacción `type='reversal'` que enlaza la original mediante `reverses_tx_id` y, de forma granular, con `reverses_entry_id` apuntando a cada asiento revertido (dirección invertida). Los ajustes contables usan `type='adjustment'` con `metadata` justificativa. Ambos quedan en la cadena de corrección (`causation_id`/`correlation_id`).
5. **Atomicidad con outbox**: el `INSERT` de asientos y la fila `outbox_events` con el evento `LedgerPosted` ocurren en la misma transacción ACID (`P-event-catalog.md` #38), de modo que no existe asiento sin evento ni evento sin asiento.
6. **Idempotencia de postings**: `ledger_idempotency_keys` con `idempotency_key` (PK) + `request_hash` SHA-256 del payload canónico + respuesta almacenada (TTL 7 días). Reenvío con la misma clave y el mismo hash devuelve la misma transacción; clave repetida con payload distinto → error `IdempotencyConflict`. Mitiga R-002.
7. **Retención**: asientos y transacciones financieras son **permanentes** (sin `DROP`/`DELETE`; ver ADR-0014). Cuentas inactivas se cierran con `closed_at`. Solo `ledger_idempotency_keys` (7 días) y `outbox_events` (30 días tras publicar) se purgan por TTL.
8. **Minimización de PII en el ledger**: los asientos referencian `owner_id` (UUID) y moneda; los datos personales viven en `identity`. Esto hace compatible la inmutabilidad permanente con la minimización de datos (`00-decisions.md` §7).
9. **Dinero tipado**: `NUMERIC(38,18)` en PostgreSQL y `decimal.Decimal` en Python, con `amount_minor BIGINT` donde la moneda lo permita; `float` prohibido (`00-decisions.md` §5).

## Consecuencias

### Positivas

- Historial financiero completo, reconstruible y auditable: cualquier saldo es reproducible en cualquier instante (`Σ entries ≤ t`).
- Detección de manipulación y de errores: reconciliación diaria ledger↔proyección con `matched` y alertas; correcciones visibles y enlazadas, no ocultas.
- Rollback de errores sin pérdida de información: la reversión añade, nunca borra; la cadena de reversión documenta el "por qué".
- Base directa para contabilidad, reportes regulatorios y reconciliación con PSP/venue (los asientos son el contrato con `payments`, `trading` y `risk`).
- Sin condiciones de carrera sobre un campo de saldo: la lectura es una agregación determinista sobre asientos indexados (`(account_id, created_at DESC)`).

### Negativas

- Crecimiento continuo de `ledger_entries`: exige particionado/retención operativa en Fase 3+ (`L-ledger-architecture.md` §10) y presupuesto de almacenamiento.
- Corrección en dos pasos (reversión + nuevo asiento) frente a un `UPDATE` directo: más código, más formación y más superficie de testing.
- Reconstrucción de saldos costosa si no se materializa `balance_after` o snapshots: trade-off `DECIDIR` en `L-ledger-architecture.md` §10 (storage vs velocidad).
- `services/ledger` se vuelve componente crítico del camino de dinero: su indisponibilidad bloquea depósitos, retiros y liquidación (se acepta; ver ADR-0019, dinero = CP).
- La inmutabilidad permanente impide el borrado físico de datos referenciados por asientos: se resuelve no persistiendo PII en el ledger (punto 8), no flexibilizando el append-only.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Saldos mutables (`UPDATE balance`) con log de auditoría aparte | No reconstruye históricos, oculta correcciones, admite pérdidas por carrera y el log puede divergir del saldo. |
| Event sourcing puro (estado solo por replay de eventos) | Consultas y extractos exigirían snapshots y replay complejo; se conservan eventos vía outbox, pero el estado persistido del ledger es la fuente. |
| Single-entry / registro de saldos por usuario | No permite invariantes de doble entrada, plan de cuentas ni reconciliación entre contrapartidas. |
| Historial de saldos mantenido por triggers sobre una tabla de balances | Sigue permitiendo `UPDATE` del saldo actual, añade lógica implícita en BD y no garantiza `Σ débitos = Σ créditos`. |
| Ledger externo / software contable de proveedor | `REQUIERE PROVEEDOR` y acoplamiento al núcleo; la regla de no-ficción (`00-decisions.md` §10) obliga a interface + adapter si algún día se integra. |

## Referencias

- `docs/phase0/00-decisions.md` §5 (dinero y consistencia), §7 (auditoría), §10 (no-ficción)
- `docs/phase0/L-ledger-architecture.md` §1 (principios), §3 (inmutabilidad), §4 (verificación), §6 (idempotencia), §8 (invariantes), §9 (retención)
- `docs/phase0/O-database-strategy.md` §4.1 (sin hard delete de datos financieros)
- `docs/phase0/G-security-architecture.md` §1.4 y §10 (tampering de ledger)
- `docs/phase0/V-risk-register.md` R-002, R-024
- `docs/phase0/A-executive-summary.md` §2 (forma arquitectónica)
- ADR-0014 (migraciones sin hard delete), ADR-0018 (tests de invariantes), ADR-0019 (CAP por subsistema)
