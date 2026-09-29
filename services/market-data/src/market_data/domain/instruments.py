"""instruments — canónico de instrumentos publicados por la portada (sección Mercados).

Verificado en vivo 2026-09-28: los cuatro códigos FX responden en Frankfurter y ECB.
ARS se excluye a propósito: el dataflow EXR del BCE dejó de publicar observaciones
diarias de ARS (última 2020-10-30) y Frankfurter no la devuelve.
"""

from __future__ import annotations

FOREX_CODES = ("USD", "GBP", "JPY")
FOREX_SYMBOLS = tuple(f"EUR/{code}" for code in FOREX_CODES)

# Par pedido en Kraken -> claves posibles en `result` (Kraken renombra XBT/ETH)
KRAKEN_KEYS: dict[str, tuple[str, ...]] = {
    "XBTUSD": ("XXBTZUSD", "XBTUSD"),
    "ETHUSD": ("XETHZUSD", "ETHUSD"),
    "USDTUSD": ("USDTZUSD", "USDTUSD"),
}
CRYPTO_PAIRS: dict[str, str] = {
    "XBTUSD": "BTC/USD",
    "ETHUSD": "ETH/USD",
    "USDTUSD": "USDT/USD",
}
COINGECKO_IDS: dict[str, str] = {
    "bitcoin": "BTC/USD",
    "ethereum": "ETH/USD",
    "tether": "USDT/USD",
}

__all__ = ["COINGECKO_IDS", "CRYPTO_PAIRS", "FOREX_CODES", "FOREX_SYMBOLS", "KRAKEN_KEYS"]
