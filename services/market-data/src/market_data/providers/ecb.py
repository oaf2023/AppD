"""ecb — FX failover directo contra el Data Portal del BCE (sin intermediario).

Batch verificado 2026-09-28:
`/EXR/D.USD%2BGBP%2BJPY.EUR.SP00.A?format=jsondata&lastNObservations=1`
(`%2B` es obligatorio: el `+` literal en el path rompe la dimensión SDMX).
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from market_data.domain.instruments import FOREX_CODES
from market_data.domain.protocols import AssetClass, ProviderError, ReferenceQuote
from market_data.domain.values import positive_float


class EcbProvider:
    provider_id: str = "ecb"
    asset_class: AssetClass = "forex"
    source: str = "Banco Central Europeo (ECB)"
    attribution: str | None = "Fuente: Banco Central Europeo (ECB)"

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def fetch_quotes(self, client: httpx.AsyncClient) -> dict[str, ReferenceQuote]:
        codes = quote("+".join(FOREX_CODES), safe="")
        response = await client.get(
            f"{self._base}/EXR/D.{codes}.EUR.SP00.A",
            params={"format": "jsondata", "lastNObservations": "1"},
        )
        response.raise_for_status()
        return self._parse(response.json())

    def _parse(self, payload: object) -> dict[str, ReferenceQuote]:
        try:
            assert isinstance(payload, dict)
            structure = payload["structure"]
            assert isinstance(structure, dict)
            series_dims = structure["dimensions"]["series"]
            time_dims = structure["dimensions"]["observation"]
            assert isinstance(series_dims, list) and isinstance(time_dims, list)
            time_values = time_dims[0]["values"]
            data_sets = payload["dataSets"]
            series = data_sets[0]["series"]
            assert isinstance(time_values, list) and isinstance(series, dict)
            currency_values = next(d["values"] for d in series_dims if d["id"] == "CURRENCY")
            currencies = [str(v["id"]) for v in currency_values]
            currency_idx = next(i for i, d in enumerate(series_dims) if d["id"] == "CURRENCY")
        except (AssertionError, KeyError, IndexError, StopIteration, TypeError) as exc:
            raise ProviderError(f"ecb: payload con forma inesperada ({exc!r})") from exc

        quotes: dict[str, ReferenceQuote] = {}
        for key, entry in series.items():
            parts = str(key).split(":")
            if len(parts) <= currency_idx:
                continue
            try:
                code = currencies[int(parts[currency_idx])]
                observations = entry["observations"]
            except IndexError, ValueError, KeyError, TypeError:
                continue
            if code not in FOREX_CODES or not isinstance(observations, dict) or not observations:
                continue
            try:
                time_idx = max(observations, key=int)
                row = observations[time_idx]
                value = positive_float(row[0]) if isinstance(row, list) and row else None
                date = str(time_values[int(time_idx)]["id"])
            except ValueError, IndexError, KeyError, TypeError:
                continue
            if value is None:
                continue
            try:
                ts = datetime.fromisoformat(date).replace(tzinfo=UTC)
            except ValueError:
                continue
            symbol = f"EUR/{code}"
            quotes[symbol] = ReferenceQuote(symbol=symbol, value=value, ts=ts)
        if not quotes:
            raise ProviderError("ecb: sin cotizaciones utilizables")
        return quotes


__all__ = ["EcbProvider"]
