import Link from "next/link";
import { defaultLocale, getMessages } from "@/i18n/messages";

/** Landing provisional de Fase 1 (placeholder, sin datos reales ni backend). */
export default function HomePage(): React.JSX.Element {
  const messages = getMessages(defaultLocale);
  const landing = messages.landing;

  const cards = [
    { title: landing.cards.foundationTitle, text: landing.cards.foundationText },
    { title: landing.cards.mockTitle, text: landing.cards.mockText },
    { title: landing.cards.i18nTitle, text: landing.cards.i18nText },
  ];

  return (
    <section aria-labelledby="titulo-portada" className="flex flex-col gap-8">
      <div className="flex flex-col items-start gap-4">
        <p className="rounded-full bg-ink px-3 py-1 text-xs font-semibold tracking-wide text-brand-300">
          {landing.badge}
        </p>
        <h1 id="titulo-portada" className="text-4xl font-bold">
          {landing.title}
        </h1>
        <p className="text-lg font-medium">{landing.subtitle}</p>
        <p className="max-w-2xl">{landing.description}</p>
        <p className="rounded bg-mist px-3 py-1 font-mono text-sm" aria-label="Estado de operativa real">
          {landing.liveFlag}
        </p>
        <Link
          href="/login"
          className="rounded bg-brand-500 px-5 py-2.5 font-semibold text-white hover:bg-brand-600"
        >
          {landing.ctaLogin}
        </Link>
      </div>

      <ul className="grid gap-4 sm:grid-cols-3">
        {cards.map((card) => (
          <li key={card.title} className="rounded-lg border border-mist bg-white p-5">
            <h2 className="mb-2 font-semibold">{card.title}</h2>
            <p className="text-sm">{card.text}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
