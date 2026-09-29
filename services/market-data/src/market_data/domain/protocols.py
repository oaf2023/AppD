"""protocols — contrato interno de un proveedor de cotizaciones."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

import httpx

AssetClass = Literal["forex", "crypto"]


class ProviderError(RuntimeError):
    """Respuesta inválida, incompleta o sin datos utilizables del proveedor."""


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    value: float
    ts: datetime


class MarketDataProvider(Protocol):
    """Agrupa todos los instrumentos de una clase de activo en un solo batch."""

    provider_id: str
    asset_class: AssetClass
    source: str
    attribution: str | None

    async def fetch_quotes(self, client: httpx.AsyncClient) -> dict[str, Quote]: ...


__all__ = ["AssetClass", "MarketDataProvider", "ProviderError", "Quote"]
