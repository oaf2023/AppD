import { Badge } from "@/components/ui";
import type { BadgeTone } from "@/components/ui";
import type { Messages } from "@/i18n/messages";
import type { MarketClassOverview } from "@/lib/market";

type MarketClassCardProps = {
  title: string;
  text: string;
  note: string;
  data: MarketClassOverview | null;
  messages: Messages;
  locale: string;
};

function formatValue(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(value);
}

/** Fechas en UTC para que el SSR sea determinista; la hora solo se muestra en crypto. */
function formatTs(ts: string, locale: string, withTime: boolean): string {
  const date = new Date(ts);
  if (!withTime) {
    return new Intl.DateTimeFormat(locale, { timeZone: "UTC", dateStyle: "medium" }).format(date);
  }
  const formatted = new Intl.DateTimeFormat(locale, {
    timeZone: "UTC",
    dateStyle: "medium",
    timeStyle: "short",
    hour12: false,
  }).format(date);
  return `${formatted} UTC`;
}

/** "Fuente: …" con la atribución del proveedor solo si aporta algo nuevo (evita "Fuente: X — Fuente: X"). */
function sourceLine(label: string, source: string, attribution: string | null): string {
  if (attribution === null) return `${label}: ${source}`;
  const text = attribution.replace(/^(Fuente|Source):\s*/i, "");
  if (text.length === 0 || source.includes(text)) return `${label}: ${source}`;
  return `${label}: ${source} — ${text}`;
}

/**
 * Card de la portada para una clase con datos reales (Forex/Crypto).
 * Estados honestos: disponible / desactualizado / no disponible — nunca cifras inventadas.
 */
export function MarketClassCard({ title, text, note, data, messages, locale }: MarketClassCardProps): React.JSX.Element {
  const copy = messages.landing.marketsData;
  const instruments = data?.instruments ?? [];
  const status = data?.status ?? "unavailable";
  const hasData = instruments.length > 0;
  const first = hasData ? instruments[0] : undefined;
  const withTime = data?.asset_class === "crypto";

  let badgeTone: BadgeTone = "warn";
  let badgeLabel = copy.unavailableBadge;
  if (status === "available" && hasData) {
    badgeTone = "info";
    badgeLabel = messages.common.availableBadge;
  } else if (status === "stale") {
    badgeLabel = copy.staleBadge;
  }

  return (
    <li className="rounded-xl border border-mist bg-white p-6 shadow-sm">
      <div className="flex flex-col items-start gap-2">
        <h3 className="text-lg font-semibold text-ink">{title}</h3>
        <p>
          <Badge tone={badgeTone}>{badgeLabel}</Badge>
        </p>
        <p className="text-sm text-ink/80">{text}</p>
        <p className="text-sm text-ink/80">{note}</p>
        {hasData ? (
          <ul className="flex w-full flex-col gap-1.5">
            {instruments.map((quote) => (
              <li key={quote.symbol} className="flex items-baseline justify-between gap-3 text-sm">
                <span className="font-mono font-semibold text-ink">{quote.symbol}</span>
                <span className="tabular-nums font-semibold text-ink">{formatValue(quote.value, locale)}</span>
                <time dateTime={quote.ts} className="text-end text-xs text-ink/70">
                  {formatTs(quote.ts, locale, withTime)}
                </time>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink/80">{copy.noData}</p>
        )}
        {status === "stale" && hasData ? <p className="text-sm text-amber-900">{copy.staleNote}</p> : null}
        {first !== undefined ? (
          <p className="text-xs text-ink/70">{sourceLine(copy.sourceLabel, first.source, first.attribution)}</p>
        ) : null}
      </div>
    </li>
  );
}
