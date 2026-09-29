"""market_data — contrato de la vista de mercados (Forex/Crypto) del servicio market-data.

Solo datos de referencia informativos de proveedores keyless (docs/API_INTEGRATIONS.md).
`simulated` queda en `false` de forma estructural hasta que G3 (X-07) habilite simulación.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AssetClass = Literal["forex", "crypto"]
ClassStatus = Literal["available", "stale", "unavailable"]


class OverviewQuote(BaseModel):
    symbol: str = Field(description="Par normalizado, p. ej. EUR/USD o BTC/USD")
    value: float = Field(gt=0, description="Último valor de referencia conocido (> 0)")
    ts: datetime = Field(
        description="UTC; en forex es la fecha de referencia diaria (00:00Z), en crypto el instante de consulta"
    )
    source: str = Field(description="Fuente del dato, p. ej. 'Banco Central Europeo (ECB) vía Frankfurter'")
    provider: str = Field(description="Id del proveedor keyless que sirvió el snapshot")
    stale: bool = Field(default=False, description="true = último dato bueno, más antiguo que el TTL")
    simulated: Literal[False] = Field(default=False, description="siempre false: G3 (X-07) está bloqueado")
    attribution: str | None = Field(default=None, description="Texto de atribución exigido por el proveedor")


class MarketClassOverview(BaseModel):
    asset_class: AssetClass
    status: ClassStatus
    instruments: list[OverviewQuote]


class MarketOverview(BaseModel):
    as_of: datetime | None = Field(default=None, description="UTC; obtención del snapshot más reciente o null")
    classes: list[MarketClassOverview]


__all__ = ["AssetClass", "ClassStatus", "MarketClassOverview", "MarketOverview", "OverviewQuote"]
