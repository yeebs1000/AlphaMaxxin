"""Provider registry — the single dependency-injection point.

Everything that needs market data receives a ProviderRegistry. The FastAPI
app builds one real registry at startup; tests build one from fakes
(tests/fakes.py) so no code path can reach the network.
"""
from dataclasses import dataclass
from functools import lru_cache

from .base import DiskTTLCache, OfflineError
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
            "orderbook": _orderbook_feed_up(),
            "ml_model": _ml_model_feed_up(),
            "altdata": True,   # keyless official APIs (wiki/iTunes/Greenhouse)
            "devdata": True,   # keyless official APIs (GitHub/npm/PyPI/Docker)
        }


def _ml_model_feed_up() -> bool:
    """The ML Alpha model feed — up once an offline-trained artifact exists and
    sklearn/joblib are installed. Pure local (no network), so unlike the order
    book it can be up under the offline tripwire; it's simply down until the
    user trains the model. See data/ml_model.py."""
    try:
        from .ml_model import model_available
        return model_available()
    except (ImportError, OfflineError):
        return False


def _orderbook_feed_up() -> bool:
    """Level 2 depth via the moomoo gateway — up when the moomoo package is
    installed and OpenD is reachable (per-ticker entitlement is still
    checked at fetch time). Reports False under the offline test tripwire."""
    try:
        from ..brokers.moomoo_client import MOOMOO_AVAILABLE, _opend_reachable
        return bool(MOOMOO_AVAILABLE) and _opend_reachable()
    except (ImportError, OfflineError):
        return False


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
