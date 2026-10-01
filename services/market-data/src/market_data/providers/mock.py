"""mock — MockMarketDataProvider determinista (BUILD-026, K §1.1/§1.3).

Driver seleccionable por settings (`create_market_data_provider`): sustituirlo
por otro driver no tocará el núcleo. Propiedades delimitadas:

- **Etiqueta**: toda respuesta sale con `simulated=True` y `source="MOCK"`
  (REQ-024). El mock jamás alimenta el snapshot informativo `GET /overview`
  (ese contrato declara `simulated=False` estructural, K §8).
- **Determinismo**: misma `seed` + mismo símbolo + mismo orden de llamadas ⇒
  misma serie, bit a bit; solo enteros y `Decimal` (ADR-0006). Los precios no
  dependen del reloj: el `ts` proviene del reloj inyectado.
- **Sin red**: ninguna firma acepta cliente HTTP; el mock no estima volumen ni
  variación de 24 h (esos campos quedan en `null`, K §2).
- **Niveles**: la serie parte de `1.0000`, camina ±50 bp por paso con spread
  sintético de 10 bp (±5 bp, factores `0.9995`/`1.0005`), dentro de límites
  `[0.01, 100]`. No reproduce precios reales de ningún mercado: es un
  generador estructural para Fases 3-4.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal

from platform_kernel.clock import utcnow

from market_data.domain.models import (
    PRICE_EXPONENT,
    AssetClass,
    CanonicalDataError,
    MarketStatus,
    ProviderCapabilities,
    Quote,
    Ticker,
)
from market_data.domain.protocols import UnknownSymbolError

PROVIDER_ID = "mock"
SOURCE = "MOCK"

#: Universo provisional del mock; el symbol master versionado llega con BUILD-028.
DEFAULT_UNIVERSE: dict[str, AssetClass] = {
    "EUR/USD": "forex",
    "GBP/USD": "forex",
    "BTC/USD": "crypto",
    "ETH/USD": "crypto",
}

_BASE = Decimal("1")
_ONE = Decimal("1")
_BPS_DIVISOR = Decimal("10000")
_MAX_STEP_BPS = 50
_BID_FACTOR = Decimal("0.9995")
_ASK_FACTOR = Decimal("1.0005")
_PRICE_FLOOR = Decimal("0.01")
_PRICE_CAP = Decimal("100")


def _step_delta(seed: int, symbol: str, step: int) -> int:
    """Desplazamiento entero en bp (-50…+50) derivado por SHA-256 del triple semilla/símbolo/paso."""
    digest = hashlib.sha256(f"{seed}\x00{symbol}\x00{step}".encode()).digest()
    raw = int.from_bytes(digest[:8], "big")
    return raw % (2 * _MAX_STEP_BPS + 1) - _MAX_STEP_BPS


class MockMarketDataProvider:
    """Implementación determinista del contrato `MarketDataProvider` (K §1.1)."""

    def __init__(
        self,
        *,
        seed: int = 42,
        symbols: Mapping[str, AssetClass] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._seed = seed
        self._symbols: dict[str, AssetClass] = dict(symbols) if symbols is not None else dict(DEFAULT_UNIVERSE)
        if not self._symbols:
            raise CanonicalDataError("mock: universo de símbolos vacío")
        self._clock: Callable[[], datetime] = clock or utcnow
        self._steps: dict[str, int] = {}
        self._series: dict[str, Decimal] = {}

    async def get_quote(self, symbol: str) -> Quote:
        self._require_symbol(symbol)
        last = self._advance(symbol)
        bid = (last * _BID_FACTOR).quantize(PRICE_EXPONENT, rounding=ROUND_DOWN)
        ask = (last * _ASK_FACTOR).quantize(PRICE_EXPONENT, rounding=ROUND_UP)
        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=last,
            ts=self._clock(),
            source=SOURCE,
            simulated=True,
        )

    async def get_tickers(self, symbols: Sequence[str] | None = None) -> list[Ticker]:
        targets = sorted(set(self._symbols) if symbols is None else set(symbols))
        for symbol in targets:
            self._require_symbol(symbol)
        return [Ticker(quote=await self.get_quote(symbol)) for symbol in targets]

    async def get_market_status(self, symbol: str | None = None) -> MarketStatus:
        if symbol is not None:
            self._require_symbol(symbol)
        return MarketStatus(
            symbol=symbol,
            status="open",
            reason="simulación continua 24/7 (mock no modela sesiones: BUILD-028)",
            as_of=self._clock(),
            source=SOURCE,
            simulated=True,
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=PROVIDER_ID,
            asset_classes=tuple(sorted(set(self._symbols.values()))),
            granularity="tick",
            supports_rest=False,
            supports_ws=False,
            simulated=True,
        )

    def _require_symbol(self, symbol: str) -> None:
        if symbol not in self._symbols:
            raise UnknownSymbolError(f"mock: símbolo desconocido: {symbol}")

    def _advance(self, symbol: str) -> Decimal:
        step = self._steps.get(symbol, 0)
        current = self._series.get(symbol, _BASE)
        delta_bps = _step_delta(self._seed, symbol, step)
        candidate = (current * (_ONE + Decimal(delta_bps) / _BPS_DIVISOR)).quantize(
            PRICE_EXPONENT, rounding=ROUND_HALF_UP
        )
        price = min(max(candidate, _PRICE_FLOOR), _PRICE_CAP)
        self._steps[symbol] = step + 1
        self._series[symbol] = price
        return price


__all__ = ["DEFAULT_UNIVERSE", "PROVIDER_ID", "SOURCE", "MockMarketDataProvider"]
