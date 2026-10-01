"""providers — adapters de market-data (Frankfurter, ECB, Kraken, CoinGecko, mock)."""

from market_data.providers.coingecko import CoinGeckoProvider
from market_data.providers.ecb import EcbProvider
from market_data.providers.factory import create_market_data_provider
from market_data.providers.frankfurter import FrankfurterProvider
from market_data.providers.kraken import KrakenProvider
from market_data.providers.mock import DEFAULT_UNIVERSE, MockMarketDataProvider

__all__ = [
    "DEFAULT_UNIVERSE",
    "CoinGeckoProvider",
    "EcbProvider",
    "FrankfurterProvider",
    "KrakenProvider",
    "MockMarketDataProvider",
    "create_market_data_provider",
]
