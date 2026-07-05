"""Provider registry — the single dependency-injection point.

Everything that needs market data receives a ProviderRegistry. The FastAPI
app builds one real registry at startup; tests build one from fakes
(tests/fakes.py) so no code path can reach the network.
"""
from dataclasses import dataclass
from functools import lru_cache

from .base import DiskTTLCache
from .yahoo import YahooProvider
from .finnhub import FinnhubProvider
from .alphavantage import AlphaVantageProvider
from .fred import FredProvider
from .yfinance_provider import YFinanceProvider


@dataclass
class ProviderRegistry:
    yahoo: YahooProvider
    finnhub: FinnhubProvider
    alphavantage: AlphaVantageProvider
    fred: FredProvider
    yfinance: YFinanceProvider

    def feed_status(self) -> dict[str, bool]:
        """Which optional feeds are configured — drives the lens registry
        (disabled lenses) and the /api/status display."""
        return {
            "yahoo": True,  # keyless
            "finnhub": self.finnhub.available,
            "alphavantage": self.alphavantage.available,
            "fred": True,   # keyless CSV path
            "yfinance": self.yfinance.available,
        }


@lru_cache(maxsize=1)
def get_default_registry() -> ProviderRegistry:
    cache = DiskTTLCache()
    return ProviderRegistry(
        yahoo=YahooProvider(cache),
        finnhub=FinnhubProvider(cache),
        alphavantage=AlphaVantageProvider(cache),
        fred=FredProvider(cache),
        yfinance=YFinanceProvider(cache),
    )
