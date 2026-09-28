import Link from "next/link";
import { defaultLocale, getMessages } from "@/i18n/messages";
import { Badge, Card, buttonClasses } from "@/components/ui";
import { AuthPanel } from "@/features/auth/AuthPanel";
import { getSessionUser } from "@/lib/auth";

/**
 * Portada de MonedasAR (estilo broker): hero dividido con propuesta de
 * valor + acceso embebido, y secciones ilustrativas honestas de lo que la
 * plataforma podrá hacer. Sin precios, saldos, estadísticas, testimonios
 * ni afirmaciones de licencia/regulación: cada capacidad no implementada
 * lleva badge de estado visible.
 */
export default async function HomePage(): Promise<React.JSX.Element> {
  const messages = getMessages(defaultLocale);
  const landing = messages.landing;
  const sessionUser = await getSessionUser();

  const marketCards = [
    { title: landing.markets.forexTitle, text: landing.markets.forexText },
    { title: landing.markets.cryptoTitle, text: landing.markets.cryptoText },
    { title: landing.markets.stocksTitle, text: landing.markets.stocksText },
    { title: landing.markets.indicesTitle, text: landing.markets.indicesText },
    { title: landing.markets.commoditiesTitle, text: landing.markets.commoditiesText },
    { title: landing.markets.etfsTitle, text: landing.markets.etfsText },
    { title: landing.markets.derivedTitle, text: landing.markets.derivedText },
  ];

  const availableCards = [
    { title: landing.available.identityTitle, text: landing.available.identityText },
    { title: landing.available.sessionsTitle, text: landing.available.sessionsText },
    { title: landing.available.auditTitle, text: landing.available.auditText },
    { title: landing.available.apiTitle, text: landing.available.apiText },
  ];

  // Reparto de fases: trading/demo/gráficos en Fase 4; pagos/copy/bots en Fase 5.
  const capabilityCards = [
    { title: landing.capabilities.leverageTitle, text: landing.capabilities.leverageText, phase: landing.soonPhase4 },
    { title: landing.capabilities.demoTitle, text: landing.capabilities.demoText, phase: landing.soonPhase4 },
    { title: landing.capabilities.chartsTitle, text: landing.capabilities.chartsText, phase: landing.soonPhase4 },
    { title: landing.capabilities.paymentsTitle, text: landing.capabilities.paymentsText, phase: landing.soonPhase5 },
    { title: landing.capabilities.copyTitle, text: landing.capabilities.copyText, phase: landing.soonPhase5 },
    { title: landing.capabilities.botsTitle, text: landing.capabilities.botsText, phase: landing.soonPhase5 },
  ];

  const stepCards = [
    { title: landing.steps.step1Title, text: landing.steps.step1Text, badge: messages.common.availableBadge, tone: "info" as const },
    { title: landing.steps.step2Title, text: landing.steps.step2Text, badge: messages.common.soonBadge, tone: "warn" as const },
    { title: landing.steps.step3Title, text: landing.steps.step3Text, badge: messages.common.soonBadge, tone: "warn" as const },
  ];

  return (
    <div className="flex flex-col gap-12">
      <section aria-labelledby="titulo-portada" className="grid items-start gap-8 lg:grid-cols-2">
        <div className="flex flex-col items-start gap-4">
          <div aria-hidden="true" className="h-1.5 w-24 rounded-full bg-gradient-to-r from-brand-500 via-brand-700 to-brand-300" />
          <p className="flex flex-wrap gap-2">
            <Badge tone="info">{landing.badge}</Badge>
            <Badge tone="neutral">{messages.common.demoBadge}</Badge>
            <Badge tone="danger">{messages.common.liveOffBadge}</Badge>
          </p>
          <h1 id="titulo-portada" className="text-4xl font-bold tracking-tight">
            {landing.title}
          </h1>
          <p className="text-lg font-medium text-brand-800">{landing.subtitle}</p>
          <p className="max-w-2xl text-ink/80">{landing.description}</p>
        </div>

        <div>
          {sessionUser !== null ? (
            <Card title={landing.sessionTitle}>
              <div className="flex flex-col items-start gap-3">
                <p className="text-sm text-ink/80">
                  {landing.sessionText} <span className="font-semibold text-ink">{sessionUser.email}</span>
                </p>
                <Link href="/panel" className={buttonClasses("primary", "lg")}>
                  {landing.goPanel}
                </Link>
              </div>
            </Card>
          ) : (
            <AuthPanel messages={messages} />
          )}
        </div>
      </section>

      <section aria-labelledby="titulo-mercados" id="mercados" className="flex scroll-mt-24 flex-col gap-4">
        <h2 id="titulo-mercados" className="text-2xl font-bold tracking-tight">
          {landing.marketsTitle}
        </h2>
        <p className="max-w-2xl text-ink/80">{landing.marketsText}</p>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {marketCards.map((card) => (
            <li key={card.title} className="rounded-xl border border-mist bg-white p-6 shadow-sm">
              <div className="flex flex-col items-start gap-2">
                <h3 className="text-lg font-semibold text-ink">{card.title}</h3>
                <p>
                  <Badge tone="warn">{landing.marketsBadge}</Badge>
                </p>
                <p className="text-sm text-ink/80">{card.text}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="titulo-disponible" className="flex flex-col gap-4">
        <h2 id="titulo-disponible" className="text-2xl font-bold tracking-tight">
          {landing.availableTitle}
        </h2>
        <p className="max-w-2xl text-ink/80">{landing.availableText}</p>
        <ul className="grid gap-4 sm:grid-cols-2">
          {availableCards.map((card) => (
            <li key={card.title} className="rounded-xl border border-mist bg-white p-6 shadow-sm">
              <div className="flex flex-col items-start gap-2">
                <h3 className="text-lg font-semibold text-ink">{card.title}</h3>
                <p>
                  <Badge tone="info">{messages.common.availableBadge}</Badge>
                </p>
                <p className="text-sm text-ink/80">{card.text}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="titulo-capacidades" className="flex flex-col gap-4">
        <h2 id="titulo-capacidades" className="text-2xl font-bold tracking-tight">
          {landing.capabilitiesTitle}
        </h2>
        <p className="max-w-2xl text-ink/80">{landing.capabilitiesText}</p>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {capabilityCards.map((card) => (
            <li key={card.title} className="rounded-xl border border-mist bg-white p-6 shadow-sm">
              <div className="flex flex-col items-start gap-2">
                <h3 className="text-lg font-semibold text-ink">{card.title}</h3>
                <p>
                  <Badge tone="warn">{card.phase}</Badge>
                </p>
                <p className="text-sm text-ink/80">{card.text}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="titulo-pasos" className="flex flex-col gap-4">
        <h2 id="titulo-pasos" className="text-2xl font-bold tracking-tight">
          {landing.stepsTitle}
        </h2>
        <p className="max-w-2xl text-ink/80">{landing.stepsText}</p>
        <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {stepCards.map((step, index) => (
            <li key={step.title} className="rounded-xl border border-mist bg-white p-6 shadow-sm">
              <div className="flex flex-col items-start gap-2">
                <p aria-hidden="true" className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-800 text-base font-bold text-white">
                  {index + 1}
                </p>
                <h3 className="text-lg font-semibold text-ink">{step.title}</h3>
                <p>
                  <Badge tone={step.tone}>{step.badge}</Badge>
                </p>
                <p className="text-sm text-ink/80">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="titulo-legal">
        <div
          role="note"
          aria-label={messages.common.liveOffBadge}
          className="flex flex-col gap-2 rounded-lg border border-red-800/30 bg-red-50 p-4"
        >
          <h2 id="titulo-legal" className="text-lg font-semibold text-ink">
            {landing.legalTitle}
          </h2>
          <p>
            <Badge tone="danger">{messages.common.liveOffBadge}</Badge>
          </p>
          <p className="text-sm text-ink/80">{landing.liveNotice}</p>
          <p className="text-sm text-ink/80">{landing.legalNote}</p>
          <p>
            <Badge tone="neutral" mono>
              {landing.liveFlag}
            </Badge>
          </p>
        </div>
      </section>
    </div>
  );
}
