import type { Metadata, Viewport } from "next";
import { defaultLocale, getMessages, localeDir } from "@/i18n/messages";
import { SiteHeader } from "@/components/SiteHeader";
import { getSessionUser } from "@/lib/auth";
import "./globals.css";

export const metadata: Metadata = {
  title: "MonedasAR",
  description: "Plataforma de trading de derivados OTC de MonedasAR — Fase 1 foundation, sin operativa real.",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "MonedasAR",
  },
};

// UI clara: el color del tema acompaña a la superficie principal (`paper`).
export const viewport: Viewport = {
  themeColor: "#f6f8fb",
};

/**
 * Layout raíz (idioma español, dirección preparada para RTL vía `localeDir`).
 * ADR-0015: `lang`/`dir` cambian por locale en runtime sin recarga; el
 * contenido usa utilidades lógicas de Tailwind para el espejo RTL.
 */
export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>): Promise<React.JSX.Element> {
  const messages = getMessages(defaultLocale);
  const dir = localeDir[defaultLocale] ?? "ltr";
  const sessionUser = await getSessionUser();
  const year = new Date().getFullYear();

  return (
    <html lang={defaultLocale} dir={dir}>
      <body className="flex min-h-screen flex-col bg-paper text-ink antialiased">
        <a
          href="#contenido"
          className="sr-only focus:not-sr-only focus:absolute focus:start-4 focus:top-4 focus:rounded focus:bg-ink focus:px-4 focus:py-2 focus:text-white"
        >
          {messages.common.skipLink}
        </a>
        <SiteHeader messages={messages} isAuthenticated={sessionUser !== null} />

        <main id="contenido" className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">
          {children}
        </main>

        <footer className="border-t border-mist">
          <div className="mx-auto flex w-full max-w-5xl flex-col gap-1 px-6 py-6 text-sm text-ink/80">
            <p>
              {messages.footer.foundation} · {messages.footer.liveFlag}
            </p>
            <p>{messages.footer.demoNote}</p>
            <p>
              {year} · {messages.footer.rights}
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
