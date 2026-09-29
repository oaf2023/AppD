"""schemas — schemas locales de system (HealthOut) del Market Data Service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthOut(BaseModel):
    service: str
    status: Literal["ok", "degraded"]
    version: str


__all__ = ["HealthOut"]
