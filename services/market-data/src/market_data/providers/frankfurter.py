"""frankfurter — FX primario (API keyless, proyecto MIT con datos del BCE).

Batch verificado 2026-09-28: `/v2/rates?base=eur&quotes=usd,gbp,jpy&providers=ecb`
devuelve `[{date, base, quote, rate}]` (ARS no está: el BCE dejó de publicarla).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from market_data.domain.instruments import FOREX_CODES
from market_data.domain.protocols import AssetClass, ProviderError, ReferenceQuote
from market_data.domain.values import positive_float


class FrankfurterProvider:
    provider_id: str = "frankfurter"
    asset_class: AssetClass = "forex"
    source: str = "Banco Central Europeo (ECB) vía Frankfurter"
    attribution: str | None = "Fuente: Banco Central Europeo (ECB)"

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def fetch_quotes(self, client: httpx.AsyncClient) -> dict[str, ReferenceQuote]:
        response = await client.get(
            f"{self._base}/rates",
            params={"base": "EUR", "quotes": ",".join(FOREX_CODES), "providers": "ecb"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ProviderError(f"frankfurter: payload inesperado ({type(payload).__name__})")
        quotes: dict[str, ReferenceQuote] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            code = row.get("quote")
            rate = positive_float(row.get("rate"))
            date = row.get("date")
            if not isinstance(code, str) or code not in FOREX_CODES or rate is None or not isinstance(date, str):
                continue
            try:
                ts = datetime.fromisoformat(date).replace(tzinfo=UTC)
            except ValueError:
                continue
            symbol = f"EUR/{code}"
            quotes[symbol] = ReferenceQuote(symbol=symbol, value=rate, ts=ts)
        if not quotes:
            raise ProviderError("frankfurter: sin cotizaciones utilizables")
        return quotes


__all__ = ["FrankfurterProvider"]
