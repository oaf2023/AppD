import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { defaultLocale, getMessages, localeDir } from "@/i18n/messages";
import { BrandMark } from "@/features/brand";
import "./globals.css";

export const metadata: Metadata = {
  title: "[PROJECT_NAME]",
  description: "Shell inicial de la plataforma [PROJECT_NAME] de [BRAND_NAME] — Fase 1 foundation.",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "[PROJECT_NAME]",
  },
};

export const viewport: Viewport = {
  themeColor: "#0b1220",
};

/**
 * Layout raíz (idioma español, dirección preparada para RTL vía `localeDir`).
 * ADR-0015: `lang`/`dir` cambian por locale en runtime sin recarga; el
 * contenido usa utilidades lógicas de Tailwind para el espejo RTL.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>): React.JSX.Element {
  const messages = getMessages(defaultLocale);
  const dir = localeDir[defaultLocale] ?? "ltr";

  return (
    <html lang={defaultLocale} dir={dir}>
      <body className="flex min-h-screen flex-col bg-paper text-ink antialiased">
        <a
          href="#contenido"
          className="sr-only focus:not-sr-only focus:absolute focus:start-4 focus:top-4 focus:rounded focus:bg-ink focus:px-4 focus:py-2 focus:text-white"
        >
          Saltar al contenido
        </a>
        <header className="border-b border-mist bg-ink text-white">
          <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-4">
            <Link href="/" className="flex items-center gap-3">
              <BrandMark className="h-9 w-9" />
              <span className="flex flex-col">
                <strong className="text-lg leading-tight">[PROJECT_NAME]</strong>
                <small className="text-sm text-brand-300">{messages.brand.tagline}</small>
              </span>
            </Link>
            <nav aria-label="Principal" className="flex items-center gap-2">
              <Link
                href="/"
                className="rounded px-3 py-2 text-sm hover:bg-ink-soft focus-visible:outline-brand-400"
              >
                {messages.nav.home}
              </Link>
              <Link
                href="/login"
                className="rounded bg-brand-500 px-3 py-2 text-sm font-semibold hover:bg-brand-600"
              >
                {messages.nav.login}
              </Link>
            </nav>
          </div>
        </header>

        <main id="contenido" className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">
          {children}
        </main>

        <footer className="border-t border-mist">
          <div className="mx-auto flex w-full max-w-5xl flex-col gap-1 px-6 py-6 text-sm">
            <p>
              {messages.footer.foundation} · {messages.footer.liveFlag}
            </p>
            <p>{messages.footer.rights}</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
