# ADR-0006 — Representación del dinero: nunca float; NUMERIC(38,18)/Decimal + amount_minor y reglas de redondeo explícitas

- **Estado:** Aceptada
- **Fecha:** 2026-09-27
- **ADR relacionados:** ADR-0003 (lenguaje), ADR-0005 (datos/ledger), ADR-0010 (idempotencia)

## Contexto

El sistema calcula comisiones, conversiones, margen y PnL sobre derivados OTC con múltiples monedas. Usar `float`/`double` introduce error de representación binaria (1.1 + 2.2 ≠ 3.3) que, acumulado en un ledger append-only, produce saldos que no cuadran y reconciliaciones imposibles de explicar. Existen además tres superficies distintas (PostgreSQL, Python, JavaScript/JSON) con tipos por defecto incompatibles y, en Python, un redondeo por defecto (`ROUND_HALF_EVEN`) distinto del de PostgreSQL (`round(numeric)` = *half away from zero*), lo que haría que el mismo importe redondeara distinto según dónde se calculara.

## Decisión

### 1. Tipos

| Superficie | Regla |
|---|---|
| PostgreSQL | `numeric(38,18)` para todo importe; **prohibido** `float`/`real`/`double precision` (CI inspecciona migraciones nuevas) |
| Python | `decimal.Decimal` con contexto explícito; **prohibido** `float` en cualquier cálculo monetario (mypy + revisión) |
| API/JSON | cadena decimal (`"1234.56789012"`) + `currency` ISO 4217 (`char(3)`); **nunca** número JSON de coma flotante para dinero |
| Frontend | dinero como string; parsing con librería decimal; TypeScript `strict` impide operar con `number` en campos monetarios |
| Unidades mínimas | además del monto, `amount_minor BIGINT` para monedas con exponente 0/2/3 (ISO 4217): `amount_minor = amount × 10^exp` exacta; monedas sin unidad mínima o con exponente negativo → solo `amount` |

`amount_minor` existe para casar con PSPs, motores de orden y monedas enteras; **la columna autoritativa sigue siendo `numeric(38,18)`**, y la invariante `amount_minor ↔ amount` se verifica en tests (`tests/invariantes/`, hypothesis).

### 2. Redondeo explícito (única política)

- **Modo canónico: `ROUND_HALF_UP`** (redondeo comercial, hacia fuera en el empate). Es coherente con `round(numeric)` de PostgreSQL, de modo que SQL y Python coinciden.
- Python usa `ROUND_HALF_EVEN` por defecto: el contexto se fija **explícitamente** en los helpers de dinero de `platform-kernel`; ninguna regla de negocio redondea con el contexto global implícito.
- **Quién redondea**: solo el servicio dueño del cálculo, y una sola vez: `trading` para comisiones/financiación, `payments` para conversiones de moneda, `accounts`/`risk` para límites y márgenes. **`ledger` no redondea**: recibe importes ya finales, valida escala ≤ 18 y la conversión a `amount_minor`.
- **Cuándo se redondea**: (a) cálculo de comisión/fee/impuesto antes de persistir; (b) conversión de moneda → siempre a la escala de la moneda destino con `ROUND_HALF_UP`; (c) conversión `amount ↔ amount_minor`; (d) presentación en UI (formato de visualización, **no** se persiste el valor redondeado de pantalla).
- **Qué nunca se redondea**: acumulados intermedios (PnL, sumas de asientos, balances): se suman valores ya redondeados con aritmética decimal exacta. Prohibido "redondear por si acaso" en varias capas.
- **Trazabilidad**: toda fila de fee/conversión persiste la tasa aplicada, la escala y el modo de redondeo usados, para reproducir el cálculo en auditoría.

### 3. Verificación

- Tests con `hypothesis`: propiedades adversariales (Σ entradas = 0, idempotencia ante reintentos, redondeo determinista, `amount_minor` consistente, ausencia de `float` en el camino).
- Test de fronttera que intenta escribir dinero como `float` en el ORM y debe fallar.

## Consecuencias

### Positivas

- Cero error de punto flotante: los saldos cuadran al centésimo y la reconciliación ledger↔wallet es exacta.
- Misma respuesta en SQL, Python y cliente: una sola política de redondeo verificable.
- `amount_minor` elimina ambigüedades al integrar con sistemas de unidades enteras.
- Reproducibilidad total para auditoría: tasa + escala + modo de redondeo quedan registrados.

### Negativas

- Más complejidad y CPU que `float` (Decimal es más lento); se mitiga acotando la escala y no re-calculando acumulados.
- Serialización como string obliga a cuidar el formato en APIs y a no confiar en el parseo del cliente.
- Prohíbe usar librerías numéricas basadas en `float` (numpy por defecto) para dinero: hay que pasar por `Decimal` o enteros exactos.
- El redondeo debe ocurrir en puntos concretos del código: si un servicio redondea donde no debe, el importe se desvía; se controla con revisión y tests de invariantes.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| **`float`/`double`/`number` en JS** | Error de representación binaria acumulativo; incompatible con dinero auditado. Prohibido por `00-decisions.md` §5. |
| **Solo unidades mínimas en `BIGINT`** | No representa tasas, swaps ni tasas de 8+ decimales de cripto/derivados; obliga a convenciones ad hoc por moneda. |
| **`numeric` sin política de redondeo** | SQL y Python redondean distinto en empates: el mismo cálculo daría resultados distintos según la capa. |
| **Dinero como `string` sin tipo fuerte** | Sin validación ni aritmética; los errores aparecen en tiempo de ejecución y fuera de la DB. |
| **`ROUND_HALF_EVEN` (banker's) como modo global** | Reduce sesgo estadístico, pero diverge del `round()` de PostgreSQL y es menos predecible para comisiones mostradas al usuario; se descarta como modo canónico (queda permitido solo en analytics, nunca en el camino financiero). |

## Referencias

- `docs/phase0/00-decisions.md` §5 (nunca float, `NUMERIC(38,18)` + `amount_minor`).
- `docs/phase0/O-database-strategy.md` §3 (tipos canónicos), §6 (concurrencia de saldos).
- `docs/phase0/L-ledger-architecture.md` §1–§2 (importes siempre positivos, `numeric(38,18)`).
- `docs/phase0/M-tech-stack.md` §9 (hypothesis: redondeo determinista, sin `float`).
- `docs/phase0/Q-api-map.md` §1.1 (dinero como cadena decimal en JSON).
- `docs/adr/ADR-0003-lenguaje-de-servicio.md`, `docs/adr/ADR-0005-base-de-datos-por-servicio.md`.
