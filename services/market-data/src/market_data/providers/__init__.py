"""providers — adapters keyless de market-data (Frankfurter, ECB, Kraken, CoinGecko)."""

from market_data.providers.coingecko import CoinGeckoProvider
from market_data.providers.ecb import EcbProvider
from market_data.providers.frankfurter import FrankfurterProvider
from market_data.providers.kraken import KrakenProvider

__all__ = ["CoinGeckoProvider", "EcbProvider", "FrankfurterProvider", "KrakenProvider"]
