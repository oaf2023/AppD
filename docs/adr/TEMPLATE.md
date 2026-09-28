# ADR-NNNN — Título de la decisión

- **Estado:** `Propuesta` / `Aceptada` / `Obsoleta` *(los ADR-0001…0020 publicados están `Aceptada`; ADR-0012 y ADR-0020 usan alternativamente una tabla `| Campo | Valor |` — ambas cabeceras son válidas)*
- **Fecha:** `AAAA-MM-DD`
- **ADR relacionados:** ADR-XXXX (tema), ADR-YYYY (tema)

> **Cómo usar esta plantilla:** copiar este fichero a `docs/adr/ADR-NNNN-<slug>.md` con el siguiente número correlativo libre (hoy el último es ADR-0020). No reciclar números: un ADR retirado conserva su número con estado `Obsoleta` (`README.md` §Reglas). Un cambio que invalide un ADR requiere un **nuevo ADR** (no editar el histórico) y actualizar `docs/phase0/00-decisions.md` si es fuente de verdad afectada.

## Contexto

Qué hechos, requisitos (REQ-### de `docs/phase0/B-requirements-matrix.md`), restricciones y alternativas conocidas condicionan la elección. Enlazar ficheros reales (`docs/phase0/…`, código, tablas). Si algo no está verificado, marcarlo `PENDIENTE` / `REQUIERE PROVEEDOR` / `REQUIERE DECISIÓN` — nunca inventar proveedores, contratos ni credenciales (`00-decisions.md` §10).

## Decisión

La decisión tomada, con reglas numeradas y verificables (tablas de parámetros, contratos, criterios de activación). Incluir el alcance (servicios/entornos afectados) y qué queda explícitamente fuera.

## Consecuencias

### Positivas

- …

### Negativas

- … *(toda decisión tiene coste: deuda operativa, superficie nueva, riesgo aceptado)*

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| … | … |

## Referencias

- `docs/phase0/00-decisions.md` §…
- `docs/phase0/<documento>.md` §…
- `docs/adr/ADR-XXXX-….md`

---

*Tras crear el ADR, registrarlo en `docs/adr/README.md` (tabla de índice) con número, título y tema.*
