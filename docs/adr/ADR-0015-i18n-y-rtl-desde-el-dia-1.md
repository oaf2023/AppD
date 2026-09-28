# ADR-0015 — Internacionalización y RTL desde el día 1

| Campo | Valor |
|---|---|
| **Estado** | Aceptada |
| **Fecha** | 2026-09-27 |
| **Alcance** | `apps/web` (Next.js 15), `apps/admin-shell`, `packages/ui`, contratos de API |
| **Fuente canónica** | `docs/phase0/00-decisions.md` §4 (frontend i18n/RTL) · `docs/phase0/C-gap-analysis.md` §13 · `docs/phase0/W-build-now.md` BUILD-061 |

## Contexto

- `00-decisions.md` §4 justifica Next.js 15 en parte por su capacidad de i18n/RTL; `C-gap-analysis.md` §13 declara la i18n como brecha `NO EXISTE` y REQ-065/REQ-118 fijan los requisitos (fallback, RTL, formatos ICU, UTC en API).
- `S-mvp-scope.md` §3.4 incluye en el MVP el cambio de idioma a `es`/`en`/`ar` con layout espejo, lo que confirma que el árabe (RTL) debe estar previsto en la estructura, no "añadido" en Fase 8.
- Retrofit de i18n en una UI con cadenas hardcodeadas obliga a reescribir todas las vistas, rehacer tests y corregir layouts: es el motivo clásico de retraso en fases tardías (por eso REQ-065 está en Fase 8 pero su **estructura** nace en Fase 1, BUILD-061).
- Un dato financiero mal formateado (redondeo, separadores, moneda) es un defecto de correctitud, no de estética: `00-decisions.md` §5 prohíbe `float` y exige `Decimal`/`NUMERIC(38,18)`.
- Los textos legales y de riesgo pueden exigir contenido por jurisdicción (`R-026`), por lo que el sistema debe poder versionar y sustituir cadenas por locale/jurisdicción.

## Decisión

1. **Estructura i18n creada en Fase 1**, con catálogos de mensajes para `en` y `es` como idiomas iniciales completos y **soporte preparado para 7 locales**, entre ellos `ar` (RTL). El conjunto definitivo de 7 locales se fija con Producto/Legal (`DECIDIR`) sin cambiar el mecanismo; añadir un locale nuevo = añadir catálogo + metadatos de locale, no tocar código de vistas.
2. **Ningún texto hardcodeado**: toda cadena visible pasa por el catálogo con clave tipada (un catálogo por locale, mismo set de claves, verificado en CI). Regla de lint/ESLint que prohíbe literales de texto en JSX/atributos accesibles (`aria-label`, `title`, `alt`) fuera de allowlist (números, símbolos). Test de CI que detecta claves faltantes o sobrantes por locale y hace **fallback** al idioma base sin crash (REQ-065).
3. **Formatos por locale con ICU**: fechas, horas, números, porcentajes y monedas se formatean en el cliente/servidor con `Intl`/ICU (`next-intl` o `formatjs`, librerías OSS ya citadas en `W-build-now.md` BUILD-061). La API siempre entrega **UTC canónico** (RFC3339) y montos como texto decimal; la conversión a zona del usuario se hace solo al presentar (REQ-118).
4. **RTL de primera clase**: el locale declara `dir` (`ltr`/`rtl`) y `lang`; el layout usa **propiedades lógicas** de Tailwind (`ps-`/`pe-`/`ms-`/`me-`, `start`/`end`) en lugar de `left`/`right`, sin transformaciones manuales de `transform: scaleX(-1)`. El `html[dir]` cambia en runtime sin recarga. Tests: snapshot del shell con `dir=rtl`, Playwright con locale `ar` y verificación de que el dock/paneles se espejan (`S-mvp-scope.md` §3.4).
5. **Decimal sin pérdidas en cliente**: los montos viajan por API serializados como **string** (`"1234.5678"`) o como entero `amount_minor` cuando la moneda lo permite; el cliente opera con una librería decimal de precisión arbitraria y **prohíbe** `parseFloat`/`Number()`/`toFixed` en rutas de dinero (regla de lint en `apps/web` y `packages/ui`). El backend mantiene `Decimal`/`NUMERIC(38,18)` (`00-decisions.md` §5). Solo se redondea en la capa de presentación, con la política de redondeo de la moneda declarada.
6. **Identidad visual y textos propios**: los catálogos son propiedad del proyecto (copy propio, `packages/ui`), coherente con la no reproducción de textos o assets de terceros (`00-decisions.md` §2).
7. **PWA/SSR**: los locales viven en el routing de App Router con contenido público indexable por locale (SEO), `hreflang` y fallback al contenido base; el Service Worker cachea por locale.

## Consecuencias

### Positivas

- Añadir un idioma (o jurisdicción con textos propios) es una tarea de traducción, no de refactor: sin reescritura de vistas ni de tests.
- Layouts correctos en mercados RTL desde el primer componente (evita la reescritura de estilos más costosa de todas).
- Formatos y monedas consistentes por locale y correctitud financiera preservada (sin pérdidas de precisión en cliente).
- Cumplimiento temprano de REQ-065/REQ-118 como objetivo de diseño, con tests automatizados que impiden regresiones (cadena dura nueva rompe el lint).
- El fallback garantiza que un locale incompleto degrada a texto base en lugar de mostrar claves o romper la UI.

### Negativas

- Overhead inicial en Fase 1: catálogos, lint de cadenas, tests por locale y doble mantenimiento `en`/`es` (se acepta porque BUILD-061 ya lo contempla).
- Textos dinámicos (montos, fechas, plurales, honoríficos) requieren mensajes ICU con parámetros: más complejos que concatenar strings.
- Los 7 locales completarlos implica coste de traducción y revisión legal de textos de riesgo (`REQUIERE` revisión por jurisdicción); hasta entonces solo `en`/`es` están cubiertos y el resto depende de catálogos aún no existentes (marcado como `PENDIENTE`).
- Tests de snapshot RTL sensibles al cambio de cualquier componente (ruido en PRs).
- El formateo en cliente añade pequeño coste de CPU y riesgo de divergencia con reportes del servidor si no se comparte la misma librería/política de redondeo → se comparte `packages/` de formato.

## Alternativas consideradas

| Alternativa | Motivo de descarte |
|---|---|
| Añadir i18n en Fase 8 (como indica REQ-065) dejando cadenas hardcodeadas hasta entonces | Reescritura total de vistas y tests, layouts RTL imposibles de "parchear" y congelación de features durante la migración; el coste crece con cada pantalla nueva. |
| Internacionalizar solo a inglés (un único idioma) | Excluye mercados hispanohablantes y bloquea el RTL previsto en el MVP; no satisface REQ-065/REQ-118. |
| Traducción automática en runtime / servicio de traducción externo | `REQUIERE PROVEEDOR`, textos de riesgo/legal no verificables y riesgo de fugas de contenido; la traducción debe ser un artefacto versionado. |
| Cadenas en base de datos (CMS) en lugar de catálogos versionados | Pierde type-safety, review por PR, tests de claves y despliegue atómico con el código; añade un servicio crítico en el camino de render. |
| Montos como `number` en JSON y `toFixed(2)` en cliente | Pérdida de precisión en `Decimal`/`NUMERIC(38,18)`, errores de redondeo en dinero; prohibido por `00-decisions.md` §5. |

## Referencias

- `docs/phase0/00-decisions.md` §4 (frontend i18n/RTL), §5 (Decimal), §2 (textos propios)
- `docs/phase0/C-gap-analysis.md` §13; `docs/phase0/B-requirements-matrix.md` REQ-065, REQ-118
- `docs/phase0/W-build-now.md` BUILD-061; `docs/phase0/S-mvp-scope.md` §3.4 (es/en/ar, RTL)
- `docs/phase0/M-tech-stack.md` §2 (Next.js, Tailwind, `packages/ui`)
- `docs/phase0/N-monorepo-structure.md` (`apps/web`, `packages/ui`, rutas App Router)
- `docs/phase0/V-risk-register.md` R-026 (requisitos por jurisdicción)
- ADR-0012 (flags por jurisdicción que pueden condicionar textos por región)
