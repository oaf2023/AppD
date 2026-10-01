"""protocols — contratos internos de proveedores de market-data (K §1.1, BUILD-026).

Dos contratos distintos, sin colisión de nombres:

- `OverviewProvider`: batch por clase de activo para el snapshot informativo
  `GET /overview` (excepción verificada K §8; sus valores son de referencia y no
  llevan etiqueta `simulated`; deuda conocida de decimalización en `ReferenceQuote`).
- `MarketDataProvider`: contrato canónico §1.1 (quote/tickers/status/capabilities)
  con tipos de `domain.models`; cualquier driver —mock o real— se sustituye sin
  tocar el núcleo.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx

from market_data.domain.models import (
    AssetClass,
    MarketStatus,
    ProviderCapabilities,
    Quote,
    Ticker,
)


class ProviderError(RuntimeError):
    """Respuesta inválida, incompleta o sin datos utilizables del proveedor."""


class UnknownSymbolError(ProviderError):
    """El símbolo solicitado no existe en el universo del proveedor (fail-closed)."""


@dataclass(frozen=True, slots=True)
class ReferenceQuote:
    """Valor único de referencia para el snapshot de portada (K §8, deuda a Decimal)."""

    symbol: str
    value: float
    ts: datetime


class OverviewProvider(Protocol):
    """Agrupa todos los instrumentos de una clase de activo en un solo batch."""

    provider_id: str
    asset_class: AssetClass
    source: str
    attribution: str | None

    async def fetch_quotes(self, client: httpx.AsyncClient) -> dict[str, ReferenceQuote]: ...


class MarketDataProvider(Protocol):
    """Contrato canónico de K §1.1: sin cliente HTTP en la firma (el transporte es del adapter)."""

    async def get_quote(self, symbol: str) -> Quote: ...

    async def get_tickers(self, symbols: Sequence[str] | None = None) -> list[Ticker]: ...

    async def get_market_status(self, symbol: str | None = None) -> MarketStatus: ...

    def capabilities(self) -> ProviderCapabilities: ...


__all__ = [
    "AssetClass",
    "MarketDataProvider",
    "OverviewProvider",
    "ProviderError",
    "ReferenceQuote",
    "UnknownSymbolError",
]
