/**
 * Catálogo de mensajes mínimo de `apps/web` (Fase 1 — foundation).
 *
 * Decisiones aplicadas (ADR-0015):
 * - El español (`es`) es el idioma por defecto de la UI.
 * - `es` es la fuente de verdad del conjunto de claves: `en` se tipa como
 *   `Messages`, de modo que TypeScript exige el MISMO set de claves en cada
 *   locale (ni faltantes ni sobrantes).
 * - `getMessages()` aplica fallback al idioma base sin romper la UI si el
 *   locale no existe (REQ-065).
 * - Cada locale declara su dirección de escritura (`ltr`/`rtl`); el layout
 *   usa utilidades lógicas de Tailwind (`ms-`/`me-`/`ps-`/`pe-`/`start`/`end`)
 *   para que el espejo RTL no requiera reescritura de estilos.
 *
 * PENDIENTE (Producto/Legal): los 7 locales definitivos, entre ellos `ar`
 * (RTL). Añadir un locale = añadir catálogo + entrada en `localeDir`, sin
 * tocar las vistas.
 */

export const defaultLocale = "es" as const;

/** Locales con catálogo completo en Fase 1. */
export const locales = ["es", "en"] as const;
export type Locale = (typeof locales)[number];

/** Dirección de escritura por locale (`ar` preparado como RTL aunque su catálogo sea PENDIENTE). */
export const localeDir: Record<string, "ltr" | "rtl"> = {
  es: "ltr",
  en: "ltr",
  ar: "rtl",
};

const es = {
  brand: {
    tagline: "Plataforma FinTech/Trading",
  },
  nav: {
    home: "Inicio",
    login: "Acceso",
  },
  landing: {
    badge: "Fase 1 — foundation",
    title: "[PROJECT_NAME]",
    subtitle: "Shell inicial de la plataforma de [BRAND_NAME].",
    description:
      "Esta es una página de presentación provisional. Todavía no hay datos reales, ni conexión con el backend, ni operativa disponible.",
    liveFlag: "flag_live_trading=false",
    ctaLogin: "Ir al acceso (demo)",
    cards: {
      foundationTitle: "Foundation",
      foundationText: "Estructura del monorepo, contratos y observabilidad como base.",
      mockTitle: "Sin backend todavía",
      mockText: "Los formularios están en estado demo/mock y no envían datos a ningún servidor.",
      i18nTitle: "Español + RTL preparado",
      i18nText: "Catálogos tipados con fallback y layout con propiedades lógicas.",
    },
  },
  login: {
    title: "Acceso",
    subtitle: "Formulario en estado demo/mock: no llama al backend todavía.",
    mockNotice: "Demo/mock — al pulsar «Entrar» no se envía nada a ningún servidor.",
    emailLabel: "Correo electrónico",
    emailPlaceholder: "nombre@ejemplo.com",
    passwordLabel: "Contraseña",
    passwordPlaceholder: "Tu contraseña",
    submit: "Entrar",
    submitting: "Procesando…",
    mockResult: "Resultado simulado: las credenciales no se han enviado ni validado en servidor.",
    serverValidationNote: "La validación del cliente no sustituye la validación del servidor.",
    backHome: "Volver al inicio",
  },
  footer: {
    foundation: "Fase 1 — foundation",
    liveFlag: "flag_live_trading=false",
    rights: "[BRAND_NAME] — Todos los derechos reservados.",
  },
};

/*
 * Sin `as const` a propósito: las hojas se ensanchan a `string`, de modo que
 * `Messages` exige el MISMO set de claves en cada locale pero permite valores
 * traducidos distintos.
 */

/** El conjunto de claves visible de la UI. Toda cadena visible debe vivir aquí (nada hardcodeado en JSX). */
export type Messages = typeof es;

const en: Messages = {
  brand: {
    tagline: "FinTech/Trading platform",
  },
  nav: {
    home: "Home",
    login: "Sign in",
  },
  landing: {
    badge: "Phase 1 — foundation",
    title: "[PROJECT_NAME]",
    subtitle: "[BRAND_NAME] platform initial shell.",
    description:
      "This is a provisional landing page. There is no real data, no backend connection, and no trading available yet.",
    liveFlag: "flag_live_trading=false",
    ctaLogin: "Go to sign-in (demo)",
    cards: {
      foundationTitle: "Foundation",
      foundationText: "Monorepo structure, contracts and observability as the base.",
      mockTitle: "No backend yet",
      mockText: "Forms are in demo/mock state and do not send data to any server.",
      i18nTitle: "Spanish + RTL ready",
      i18nText: "Typed catalogs with fallback and logical-property layout.",
    },
  },
  login: {
    title: "Sign in",
    subtitle: "Form in demo/mock state: it does not call the backend yet.",
    mockNotice: "Demo/mock — pressing “Sign in” sends nothing to any server.",
    emailLabel: "Email address",
    emailPlaceholder: "name@example.com",
    passwordLabel: "Password",
    passwordPlaceholder: "Your password",
    submit: "Sign in",
    submitting: "Processing…",
    mockResult: "Mocked result: credentials were neither sent nor validated on a server.",
    serverValidationNote: "Client-side validation does not replace server-side validation.",
    backHome: "Back to home",
  },
  footer: {
    foundation: "Phase 1 — foundation",
    liveFlag: "flag_live_trading=false",
    rights: "[BRAND_NAME] — All rights reserved.",
  },
};

const catalogs: Record<Locale, Messages> = { es, en };

/** Devuelve el catálogo del locale pedido o el del idioma base si no existe (fallback sin crash). */
export function getMessages(locale: string): Messages {
  const found: Messages | undefined = (catalogs as Record<string, Messages>)[locale];
  return found ?? catalogs[defaultLocale];
}
