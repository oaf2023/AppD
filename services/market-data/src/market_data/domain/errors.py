"""errors — rechazos tipados del catálogo de instrumentos (W BUILD-028, REQ-025/REQ-099).

RFC 9459 problem+json vía `AppError`: cada rechazo lleva `type` propio y
`code` estable en `extra` para que el consumidor (OMS en Fase 4, UI, tests)
ramifique sin parsear texto. `MARKET_CLOSED` es el código que exige REQ-099;
`MARKET_HALTED` distingue la suspensión explícita (K §2: `halted` ≠ `closed`).
"""

from __future__ import annotations

from platform_kernel.errors import AppError


class SpecViolationError(AppError):
    """Orden fuera de la spec vigente del instrumento (REQ-025, W BUILD-028)."""

    def __init__(self, detail: str, *, code: str, symbol: str | None = None) -> None:
        super().__init__(
            422,
            "urn:platform:error:spec-violation",
            "Especificación del instrumento violada",
            detail,
            extra={"code": code, **({"symbol": symbol} if symbol else {})},
        )
        self.code = code


class MarketClosedError(AppError):
    """Mercado fuera de horario (REQ-099): `code=MARKET_CLOSED` obligatorio."""

    def __init__(self, detail: str, *, symbol: str | None = None) -> None:
        super().__init__(
            409,
            "urn:platform:error:market-closed",
            "Mercado cerrado",
            detail,
            extra={"code": "MARKET_CLOSED", **({"symbol": symbol} if symbol else {})},
        )
        self.code = "MARKET_CLOSED"


class MarketHaltedError(AppError):
    """Suspensión explícita del símbolo (REQ-099): `code=MARKET_HALTED`."""

    def __init__(self, detail: str, *, symbol: str | None = None) -> None:
        super().__init__(
            409,
            "urn:platform:error:market-halted",
            "Mercado suspendido",
            detail,
            extra={"code": "MARKET_HALTED", **({"symbol": symbol} if symbol else {})},
        )
        self.code = "MARKET_HALTED"


__all__ = ["MarketClosedError", "MarketHaltedError", "SpecViolationError"]
