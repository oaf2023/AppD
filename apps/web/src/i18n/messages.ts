/**
 * Catálogo de mensajes de `apps/web` (Fase 1 — foundation).
 *
 * Decisiones aplicadas (ADR-0015):
 * - El español (`es`) es el idioma por defecto de la UI y la fuente de verdad
 *   del conjunto de claves: `en` se tipa como `Messages`, de modo que
 *   TypeScript exige el MISMO set de claves en cada locale (ni faltantes ni
 *   sobrantes).
 * - `getMessages()` aplica fallback al idioma base sin romper la UI si el
 *   locale no existe (REQ-065).
 * - Cada locale declara su dirección de escritura (`ltr`/`rtl`); el layout
 *   usa utilidades lógicas de Tailwind (`ms-`/`me-`/`ps-`/`pe-`/`start`/`end`)
 *   para que el espejo RTL no requiera reescritura de estilos.
 * - TODA cadena visible (incluidos skip-link, aria-labels y textos de marca
 *   como `MonedasAR`) vive en este catálogo: nada hardcodeado
 *   en JSX.
 *
 * PENDIENTE (Producto/Legal): los 7 locales definitivos, entre ellos `ar`
 * (RTL), y el selector de idioma en la UI (fuera de alcance en esta fase).
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
    projectName: "MonedasAR",
    tagline: "Plataforma FinTech/Trading",
  },
  nav: {
    mainLabel: "Navegación principal",
    menuLabel: "Menú",
    menuOpen: "Abrir menú",
    menuClose: "Cerrar menú",
    home: "Inicio",
    markets: "Mercados",
    access: "Acceso",
    login: "Iniciar sesión",
    register: "Crear cuenta",
    panel: "Panel",
  },
  common: {
    skipLink: "Saltar al contenido",
    retry: "Reintentar",
    backHome: "Volver al inicio",
    loading: "Cargando…",
    soonBadge: "Próximamente",
    availableBadge: "Disponible",
    demoBadge: "Demostración",
    liveOffBadge: "Operativa real desactivada",
    fieldRequired: "Campo obligatorio",
    emailInvalid: "Introduce un correo electrónico válido.",
    emailRequired: "El correo electrónico es obligatorio.",
    passwordRequired: "La contraseña es obligatoria.",
    passwordMin: "La contraseña debe tener al menos 12 caracteres.",
    unexpectedError: "Ocurrió un error inesperado. Inténtalo de nuevo.",
  },
  landing: {
    badge: "Fase foundation",
    title: "Compra y vende monedas, criptomonedas y más",
    subtitle: "La plataforma para operar divisas, cripto y mercados globales desde una sola cuenta.",
    description:
      "Crea tu cuenta hoy: identidad segura con Argon2id y MFA opcional, sesiones auditadas y API abierta. La cuenta demo y la operativa real llegan en próximas fases.",
    liveNotice:
      "La operativa real está desactivada (flag_live_trading=false). Nada de lo mostrado aquí constituye una oferta de inversión.",
    liveFlag: "flag_live_trading=false",
    authTitle: "Empieza ahora",
    authTabLogin: "Iniciar sesión",
    authTabRegister: "Crear cuenta",
    sessionTitle: "Te damos la bienvenida",
    sessionText: "Tienes una sesión activa con esta cuenta.",
    goPanel: "Ir al panel",
    marketsTitle: "Mercados",
    marketsText:
      "Todo lo que la plataforma podrá ofrecer cuando se activen las fases de mercado. Sin precios ni operativa en esta fase.",
    marketsBadge: "Próximamente · Fases 3–4",
    markets: {
      forexTitle: "Forex",
      forexText: "Pares de divisas como EUR/USD.",
      cryptoTitle: "Criptomonedas",
      cryptoText: "Bitcoin (BTC), Ethereum (ETH) y estables como USDT.",
      stocksTitle: "Acciones",
      stocksText: "Acciones de empresas locales e internacionales.",
      indicesTitle: "Índices bursátiles",
      indicesText: "Índices que agrupan a las principales empresas.",
      commoditiesTitle: "Commodities",
      commoditiesText: "Oro, plata y petróleo.",
      etfsTitle: "ETFs",
      etfsText: "Fondos que replican índices y sectores.",
      derivedTitle: "Índices derivados 24/7",
      derivedText: "Índices sintéticos disponibles las 24 horas, los 7 días.",
    },
    availableTitle: "Disponible hoy",
    availableText: "Lo que ya puedes usar en tu cuenta de MonedasAR.",
    available: {
      identityTitle: "Registro e identidad segura",
      identityText: "Contraseñas Argon2id con MFA opcional y verificación de correo.",
      sessionsTitle: "Sesiones y control de acceso",
      sessionsText: "Tokens de corta duración con rotación y revocación inmediata.",
      auditTitle: "Auditoría inmutable",
      auditText: "Eventos de identidad con outbox transaccional para trazabilidad.",
      apiTitle: "API REST",
      apiText: "Punto de entrada único con límites de velocidad y errores estándar.",
    },
    capabilitiesTitle: "Qué podrás hacer",
    capabilitiesText: "Capacidades previstas en la hoja de ruta. Nada de esto está operativo hoy.",
    soonPhase4: "Próximamente · Fase 4",
    soonPhase5: "Próximamente · Fase 5",
    capabilities: {
      leverageTitle: "Operar con apalancamiento",
      leverageText: "Amplía tu exposición con control de riesgo.",
      demoTitle: "Cuenta demo",
      demoText: "Practica sin riesgo con saldo virtual.",
      chartsTitle: "Gráficos y análisis",
      chartsText: "Gráficos y herramientas de análisis técnico.",
      paymentsTitle: "Depósitos y retiros",
      paymentsText: "Fondea y retira por medios locales e internacionales.",
      copyTitle: "Copy trading",
      copyText: "Replica las operaciones de otros traders.",
      botsTitle: "Bots de automatización",
      botsText: "Automatiza estrategias con reglas propias.",
    },
    stepsTitle: "Cómo empezar",
    stepsText: "Tres pasos, del registro a la operativa real.",
    steps: {
      step1Title: "Regístrate",
      step1Text: "Crea tu cuenta con correo, jurisdicción y términos.",
      step2Title: "Practica en la cuenta demo",
      step2Text: "Aprende sin riesgo cuando la demo esté disponible.",
      step3Title: "Opera cuando se active la operativa real",
      step3Text: "Accede a los mercados cuando se habiliten por fase.",
    },
    legalTitle: "Aviso importante",
    legalNote: "Esto no constituye una oferta de inversión ni asesoramiento financiero.",
  },
  login: {
    title: "Iniciar sesión",
    subtitle: "Accede a tu cuenta de MonedasAR.",
    emailLabel: "Correo electrónico",
    emailPlaceholder: "nombre@ejemplo.com",
    passwordLabel: "Contraseña",
    passwordPlaceholder: "Tu contraseña",
    passwordHint: "Mínimo 12 caracteres.",
    submit: "Entrar",
    submitting: "Entrando…",
    noAccount: "¿No tienes cuenta?",
    registerLink: "Crea una cuenta",
    mfaTitle: "Verificación en dos pasos",
    mfaText:
      "Tu cuenta requiere verificación en dos pasos (código MFA). La interfaz de verificación todavía no está disponible en esta fase: inténtalo más tarde o contacta con soporte.",
    backHome: "Volver al inicio",
    serverValidationNote: "La validación del cliente no sustituye la validación del servidor.",
    globalError: "No se pudo iniciar sesión.",
  },
  register: {
    title: "Crear cuenta",
    subtitle: "Regístrate en MonedasAR. Sin operativa real en esta fase.",
    emailLabel: "Correo electrónico",
    emailPlaceholder: "nombre@ejemplo.com",
    passwordLabel: "Contraseña",
    passwordPlaceholder: "Elige una contraseña segura",
    passwordHint: "Mínimo 12 caracteres.",
    jurisdictionLabel: "Jurisdicción",
    jurisdictionHint: "País o región de tu cuenta (código ISO, p. ej. ES). La valida el servidor.",
    jurisdictionPlaceholder: "Selecciona tu jurisdicción",
    jurisdictionRequired: "La jurisdicción es obligatoria.",
    termsLabel: "Acepto los términos y condiciones.",
    termsHint: "Imprescindible para crear la cuenta. La aceptación se registra en el servidor.",
    termsRequired: "Debes aceptar los términos y condiciones.",
    submit: "Crear cuenta",
    submitting: "Creando cuenta…",
    successTitle: "Cuenta creada",
    successText:
      "Tu cuenta se creó correctamente. Si la verificación de correo está activa, revisa tu bandeja para verificarla antes de entrar.",
    loginLink: "Ir a iniciar sesión",
    hasAccount: "¿Ya tienes cuenta?",
    backHome: "Volver al inicio",
    serverValidationNote: "La validación del cliente no sustituye la validación del servidor.",
    globalError: "No se pudo crear la cuenta.",
  },
  panel: {
    title: "Panel",
    subtitle: "Resumen de tu cuenta. Sin datos de mercado en esta fase.",
    accountTitle: "Mi cuenta",
    emailLabel: "Correo",
    statusLabel: "Estado",
    rolesLabel: "Roles",
    rolesEmpty: "Sin roles asignados",
    verifiedLabel: "Correo verificado",
    verifiedYes: "Sí",
    verifiedNo: "No",
    mfaLabel: "Doble factor (MFA)",
    mfaYes: "Activado",
    mfaNo: "Desactivado",
    sessionTitle: "Sesión",
    sessionActive: "Sesión activa en este navegador (tokens en cookies httpOnly).",
    marketsTitle: "Mercados",
    marketsText: "Los datos de mercado y la operativa estarán disponibles aquí cuando se activen en fases posteriores.",
    tradingTitle: "Operativa real",
    tradingText:
      "La operativa real está desactivada en esta fase (flag_live_trading=false). Nada de lo mostrado aquí constituye una oferta de inversión.",
    logout: "Cerrar sesión",
    loggingOut: "Cerrando sesión…",
    loadError: "No se pudo cargar tu cuenta. Inténtalo de nuevo.",
  },
  notFound: {
    title: "Página no encontrada",
    description: "La página que buscas no existe o se movió. Revisa la dirección o vuelve al inicio.",
    backHome: "Volver al inicio",
    loginLink: "Ir a iniciar sesión",
  },
  pageError: {
    title: "Algo salió mal",
    description: "Ocurrió un error al cargar esta página. Puedes reintentarlo o volver al inicio.",
    retry: "Reintentar",
    backHome: "Volver al inicio",
  },
  footer: {
    foundation: "Fase 1 — foundation",
    liveFlag: "flag_live_trading=false",
    rights: "MonedasAR — Todos los derechos reservados.",
    demoNote: "Entorno de demostración: sin operativa real ni datos de mercado.",
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
    projectName: "MonedasAR",
    tagline: "FinTech/Trading platform",
  },
  nav: {
    mainLabel: "Main navigation",
    menuLabel: "Menu",
    menuOpen: "Open menu",
    menuClose: "Close menu",
    home: "Home",
    markets: "Markets",
    access: "Sign in",
    login: "Sign in",
    register: "Create account",
    panel: "Dashboard",
  },
  common: {
    skipLink: "Skip to content",
    retry: "Retry",
    backHome: "Back to home",
    loading: "Loading…",
    soonBadge: "Coming soon",
    availableBadge: "Available",
    demoBadge: "Demo",
    liveOffBadge: "Live trading disabled",
    fieldRequired: "Required field",
    emailInvalid: "Enter a valid email address.",
    emailRequired: "Email address is required.",
    passwordRequired: "Password is required.",
    passwordMin: "Password must be at least 12 characters.",
    unexpectedError: "An unexpected error occurred. Please try again.",
  },
  landing: {
    badge: "Foundation phase",
    title: "Buy and sell currencies, crypto and more",
    subtitle: "The platform to trade forex, crypto and global markets from a single account.",
    description:
      "Create your account today: secure identity with Argon2id and optional MFA, audited sessions and an open API. The demo account and live trading arrive in upcoming phases.",
    liveNotice:
      "Live trading is disabled (flag_live_trading=false). Nothing shown here is an investment offer.",
    liveFlag: "flag_live_trading=false",
    authTitle: "Get started now",
    authTabLogin: "Sign in",
    authTabRegister: "Create account",
    sessionTitle: "Welcome back",
    sessionText: "You have an active session with this account.",
    goPanel: "Go to dashboard",
    marketsTitle: "Markets",
    marketsText:
      "Everything the platform will be able to offer once the market phases are enabled. No prices or trading in this phase.",
    marketsBadge: "Coming soon · Phases 3–4",
    markets: {
      forexTitle: "Forex",
      forexText: "Currency pairs such as EUR/USD.",
      cryptoTitle: "Cryptocurrencies",
      cryptoText: "Bitcoin (BTC), Ethereum (ETH) and stablecoins such as USDT.",
      stocksTitle: "Stocks",
      stocksText: "Shares of local and international companies.",
      indicesTitle: "Stock indices",
      indicesText: "Indices grouping leading companies.",
      commoditiesTitle: "Commodities",
      commoditiesText: "Gold, silver and oil.",
      etfsTitle: "ETFs",
      etfsText: "Funds tracking indices and sectors.",
      derivedTitle: "Derived indices 24/7",
      derivedText: "Synthetic indices available 24 hours a day, 7 days a week.",
    },
    availableTitle: "Available today",
    availableText: "What you can already use in your MonedasAR account.",
    available: {
      identityTitle: "Secure registration and identity",
      identityText: "Argon2id passwords with optional MFA and email verification.",
      sessionsTitle: "Sessions and access control",
      sessionsText: "Short-lived tokens with rotation and instant revocation.",
      auditTitle: "Immutable audit",
      auditText: "Identity events with a transactional outbox for traceability.",
      apiTitle: "REST API",
      apiText: "Single entry point with rate limits and standard errors.",
    },
    capabilitiesTitle: "What you will be able to do",
    capabilitiesText: "Capabilities planned on the roadmap. None of this is live today.",
    soonPhase4: "Coming soon · Phase 4",
    soonPhase5: "Coming soon · Phase 5",
    capabilities: {
      leverageTitle: "Trade with leverage",
      leverageText: "Amplify your exposure with risk controls.",
      demoTitle: "Demo account",
      demoText: "Practise risk-free with virtual funds.",
      chartsTitle: "Charts and analysis",
      chartsText: "Charts and technical analysis tools.",
      paymentsTitle: "Deposits and withdrawals",
      paymentsText: "Fund and withdraw via local and international methods.",
      copyTitle: "Copy trading",
      copyText: "Replicate other traders' orders.",
      botsTitle: "Automation bots",
      botsText: "Automate strategies with your own rules.",
    },
    stepsTitle: "How to get started",
    stepsText: "Three steps, from registration to live trading.",
    steps: {
      step1Title: "Register",
      step1Text: "Create your account with email, jurisdiction and terms.",
      step2Title: "Practise on the demo account",
      step2Text: "Learn risk-free once the demo is available.",
      step3Title: "Trade once live trading is enabled",
      step3Text: "Access markets as they are enabled by phase.",
    },
    legalTitle: "Important notice",
    legalNote: "This is not an investment offer or financial advice.",
  },
  login: {
    title: "Sign in",
    subtitle: "Access your MonedasAR account.",
    emailLabel: "Email address",
    emailPlaceholder: "name@example.com",
    passwordLabel: "Password",
    passwordPlaceholder: "Your password",
    passwordHint: "Minimum 12 characters.",
    submit: "Sign in",
    submitting: "Signing in…",
    noAccount: "No account yet?",
    registerLink: "Create an account",
    mfaTitle: "Two-step verification",
    mfaText:
      "Your account requires two-step verification (MFA code). The verification interface is not available yet in this phase: try again later or contact support.",
    backHome: "Back to home",
    serverValidationNote: "Client-side validation does not replace server-side validation.",
    globalError: "Could not sign in.",
  },
  register: {
    title: "Create account",
    subtitle: "Register on MonedasAR. No live trading in this phase.",
    emailLabel: "Email address",
    emailPlaceholder: "name@example.com",
    passwordLabel: "Password",
    passwordPlaceholder: "Choose a strong password",
    passwordHint: "Minimum 12 characters.",
    jurisdictionLabel: "Jurisdiction",
    jurisdictionHint: "Country or region of your account (ISO code, e.g. ES). Validated by the server.",
    jurisdictionPlaceholder: "Select your jurisdiction",
    jurisdictionRequired: "Jurisdiction is required.",
    termsLabel: "I accept the terms and conditions.",
    termsHint: "Required to create the account. Acceptance is recorded on the server.",
    termsRequired: "You must accept the terms and conditions.",
    submit: "Create account",
    submitting: "Creating account…",
    successTitle: "Account created",
    successText:
      "Your account was created successfully. If email verification is enabled, check your inbox to verify it before signing in.",
    loginLink: "Go to sign in",
    hasAccount: "Already have an account?",
    backHome: "Back to home",
    serverValidationNote: "Client-side validation does not replace server-side validation.",
    globalError: "Could not create the account.",
  },
  panel: {
    title: "Dashboard",
    subtitle: "Your account summary. No market data in this phase.",
    accountTitle: "My account",
    emailLabel: "Email",
    statusLabel: "Status",
    rolesLabel: "Roles",
    rolesEmpty: "No roles assigned",
    verifiedLabel: "Email verified",
    verifiedYes: "Yes",
    verifiedNo: "No",
    mfaLabel: "Two-factor (MFA)",
    mfaYes: "Enabled",
    mfaNo: "Disabled",
    sessionTitle: "Session",
    sessionActive: "Active session in this browser (tokens in httpOnly cookies).",
    marketsTitle: "Markets",
    marketsText: "Market data and trading will be available here when enabled in later phases.",
    tradingTitle: "Live trading",
    tradingText:
      "Live trading is disabled in this phase (flag_live_trading=false). Nothing shown here is an investment offer.",
    logout: "Sign out",
    loggingOut: "Signing out…",
    loadError: "Could not load your account. Please try again.",
  },
  notFound: {
    title: "Page not found",
    description: "The page you are looking for does not exist or was moved. Check the address or go back home.",
    backHome: "Back to home",
    loginLink: "Go to sign in",
  },
  pageError: {
    title: "Something went wrong",
    description: "An error occurred while loading this page. You can retry or go back home.",
    retry: "Retry",
    backHome: "Back to home",
  },
  footer: {
    foundation: "Phase 1 — foundation",
    liveFlag: "flag_live_trading=false",
    rights: "MonedasAR — All rights reserved.",
    demoNote: "Demo environment: no live trading or market data.",
  },
};

const catalogs: Record<Locale, Messages> = { es, en };

/** Devuelve el catálogo del locale pedido o el del idioma base si no existe (fallback sin crash). */
export function getMessages(locale: string): Messages {
  const found: Messages | undefined = (catalogs as Record<string, Messages>)[locale];
  return found ?? catalogs[defaultLocale];
}
