"""kraken — Crypto primario (API pública keyless; límite 1 req/s por IP).

Batch verificado 2026-09-28: `pair=XBTUSD,ETHUSD,USDTUSD` responde `XXBTZUSD`,
`XETHZUSD` y `USDTZUSD`. El ticker no trae marca temporal: se registra el instante
de consulta (`ts`), nunca un valor sintético.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from market_data.domain.instruments import CRYPTO_PAIRS, KRAKEN_KEYS
from market_data.domain.protocols import AssetClass, ProviderError, Quote
from market_data.domain.values import positive_float


class KrakenProvider:
    provider_id: str = "kraken"
    asset_class: AssetClass = "crypto"
    source: str = "Kraken"
    attribution: str | None = None

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def fetch_quotes(self, client: httpx.AsyncClient) -> dict[str, Quote]:
        response = await client.get(
            f"{self._base}/0/public/Ticker",
            params={"pair": ",".join(CRYPTO_PAIRS)},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProviderError(f"kraken: payload inesperado ({type(payload).__name__})")
        errors = payload.get("error")
        if errors:
            raise ProviderError(f"kraken: error del API {errors!r}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ProviderError("kraken: sin campo result")

        now = datetime.now(UTC)
        quotes: dict[str, Quote] = {}
        for pair, symbol in CRYPTO_PAIRS.items():
            entry = next((result[key] for key in KRAKEN_KEYS[pair] if key in result), None)
            if not isinstance(entry, dict):
                continue
            last = entry.get("c")  # c = [último precio, volumen del lote]
            value = positive_float(last[0]) if isinstance(last, list) and last else None
            if value is None:
                continue
            quotes[symbol] = Quote(symbol=symbol, value=value, ts=now)
        if not quotes:
            raise ProviderError("kraken: sin cotizaciones utilizables")
        return quotes


__all__ = ["KrakenProvider"]
