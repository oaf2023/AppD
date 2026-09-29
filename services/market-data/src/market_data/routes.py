"""routes — endpoints del Market Data Service."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from platform_contracts.market_data import MarketOverview

from market_data.schemas import HealthOut
from market_data.service import MarketDataService

router = APIRouter()

VERSION = "0.1.0"


def _service(request: Request) -> MarketDataService:
    return request.app.state.service  # type: ignore[no-any-return]


ServiceDep = Annotated[MarketDataService, Depends(_service)]


@router.get("/healthz", response_model=HealthOut, tags=["system"])
async def healthz() -> HealthOut:
    return HealthOut(service="market-data", status="ok", version=VERSION)


@router.get("/readyz", response_model=HealthOut, tags=["system"])
async def readyz() -> HealthOut:
    # Sin dependencias locales: el proceso es la única precondición.
    # Los proveedores externos son best-effort (failover + último dato bueno).
    return HealthOut(service="market-data", status="ok", version=VERSION)


@router.get("/api/v1/market-data/overview", response_model=MarketOverview, tags=["market-data"])
async def overview(service: ServiceDep) -> MarketOverview:
    return await service.overview()


__all__ = ["router"]
