"""coingecko — Crypto failover (API pública keyless; atribución obligatoria §29).

Batch verificado 2026-09-28: `simple/price?ids=bitcoin,ethereum,tether&vs_currencies=usd`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from market_data.domain.instruments import COINGECKO_IDS
from market_data.domain.protocols import AssetClass, ProviderError, Quote
from market_data.domain.values import positive_float


class CoinGeckoProvider:
    provider_id: str = "coingecko"
    asset_class: AssetClass = "crypto"
    source: str = "CoinGecko"
    attribution: str | None = "Powered by CoinGecko"

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def fetch_quotes(self, client: httpx.AsyncClient) -> dict[str, Quote]:
        response = await client.get(
            f"{self._base}/simple/price",
            params={"ids": ",".join(COINGECKO_IDS), "vs_currencies": "usd"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProviderError(f"coingecko: payload inesperado ({type(payload).__name__})")

        now = datetime.now(UTC)
        quotes: dict[str, Quote] = {}
        for coin_id, symbol in COINGECKO_IDS.items():
            entry = payload.get(coin_id)
            value = positive_float(entry.get("usd")) if isinstance(entry, dict) else None
            if value is None:
                continue
            quotes[symbol] = Quote(symbol=symbol, value=value, ts=now)
        if not quotes:
            raise ProviderError("coingecko: sin cotizaciones utilizables")
        return quotes


__all__ = ["CoinGeckoProvider"]
