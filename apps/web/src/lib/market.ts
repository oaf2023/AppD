import { gatewayUrl } from "@/lib/auth";

/**
 * Cliente del BFF para `GET /api/v1/market-data/overview` (SOLO servidor).
 *
 * Cubre los tipos del contrato `platform_contracts.market_data.MarketOverview`.
 * Si el gateway no responde o el payload no cumple el contrato, devuelve `null`
 * y la portada muestra "dato no disponible" (sin datos inventados).
 */

const MARKET_TIMEOUT_MS = 12_000; // cubre el failover primario→secundario (2×5 s) del servicio

export type OverviewQuote = {
  symbol: string;
  value: number;
  ts: string;
  source: string;
  provider: string;
  stale: boolean;
  simulated: false;
  attribution: string | null;
};

export type MarketClassOverview = {
  asset_class: "forex" | "crypto";
  status: "available" | "stale" | "unavailable";
  instruments: OverviewQuote[];
};

export type MarketOverview = {
  as_of: string | null;
  classes: MarketClassOverview[];
};

function isQuote(value: unknown): value is OverviewQuote {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record["symbol"] === "string" &&
    typeof record["value"] === "number" &&
    record["value"] > 0 &&
    typeof record["ts"] === "string" &&
    typeof record["source"] === "string" &&
    typeof record["provider"] === "string" &&
    typeof record["stale"] === "boolean" &&
    record["simulated"] === false &&
    (record["attribution"] === null || typeof record["attribution"] === "string")
  );
}

function isMarketOverview(value: unknown): value is MarketOverview {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  const asOf = record["as_of"];
  if (asOf !== null && typeof asOf !== "string") return false;
  const classes = record["classes"];
  if (!Array.isArray(classes)) return false;
  return classes.every((entry) => {
    if (typeof entry !== "object" || entry === null) return false;
    const item = entry as Record<string, unknown>;
    const assetClass = item["asset_class"];
    const status = item["status"];
    const instruments = item["instruments"];
    return (
      (assetClass === "forex" || assetClass === "crypto") &&
      (status === "available" || status === "stale" || status === "unavailable") &&
      Array.isArray(instruments) &&
      instruments.every((quote) => isQuote(quote))
    );
  });
}

/** Snapshot actual de mercados o `null` si el servicio no respondió (la portada lo trata como "dato no disponible"). */
export async function getMarketOverview(): Promise<MarketOverview | null> {
  try {
    const response = await fetch(`${gatewayUrl()}/api/v1/market-data/overview`, {
      signal: AbortSignal.timeout(MARKET_TIMEOUT_MS),
      cache: "no-store",
    });
    if (!response.ok) return null;
    const data: unknown = await response.json();
    return isMarketOverview(data) ? data : null;
  } catch {
    return null;
  }
}
