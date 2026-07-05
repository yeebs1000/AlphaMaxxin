"""Fixture-backed fake providers for tests. Same method surface as the real
providers in app/data/, zero network. Construct with explicit data or let
them fall back to empty results."""


class FakeYahoo:
    name = "yahoo"

    def __init__(self, ohlcv_data=None, quotes=None, search_results=None, fx=None):
        self._ohlcv = ohlcv_data or {}
        self._quotes = quotes or {}
        self._search = search_results or {}
        self._fx = fx or {"USD": 1.0}

    def ohlcv(self, ticker, interval="1d", range_="1y"):
        return self._ohlcv.get(ticker)

    def quote(self, symbol):
        return self._quotes.get(symbol)

    def search(self, query, max_results=6):
        return self._search.get(query, [])[:max_results]

    def fx_rate(self, ccy):
        return self._fx.get(ccy)

    def resolve_symbol(self, query):
        results = self.search(query, max_results=1)
        if results:
            return results[0]["symbol"], results[0]["name"]
        return query.upper(), query


class FakeFinnhub:
    name = "finnhub"

    def __init__(self, news=None, metrics=None, earnings=None, ipos=None, available=True):
        self._news = news or {}
        self._metrics = metrics or {}
        self._earnings = earnings or []
        self._ipos = ipos or []
        self.available = available

    def news(self, ticker, days=7):
        return self._news.get(ticker.replace(".SI", "").upper(), [])

    def metrics(self, ticker):
        return self._metrics.get(ticker.replace(".SI", "").upper())

    def earnings_calendar(self, from_date, to_date):
        return self._earnings

    def ipo_calendar(self, from_date, to_date):
        return self._ipos


class FakeAlphaVantage:
    name = "alphavantage"

    def __init__(self, news=None, available=True):
        self._news = news or {}
        self.available = available

    def news(self, ticker):
        return self._news.get(ticker.replace(".SI", "").upper(), [])


class FakeFred:
    name = "fred"
    available = True

    def __init__(self, series_data=None):
        self._series = series_data or {}

    def series(self, series_id, limit=400):
        return self._series.get(series_id)


class FakeYFinance:
    name = "yfinance"

    def __init__(self, fundamentals=None, option_chains=None, available=True):
        self._fundamentals = fundamentals or {}
        self._chains = option_chains or {}
        self.available = available

    def fundamentals(self, ticker):
        return self._fundamentals.get(ticker)

    def option_chain(self, ticker):
        return self._chains.get(ticker)


def make_registry(**overrides):
    """A ProviderRegistry built entirely from fakes; override any slot."""
    from app.data.registry import ProviderRegistry
    return ProviderRegistry(
        yahoo=overrides.get("yahoo", FakeYahoo()),
        finnhub=overrides.get("finnhub", FakeFinnhub()),
        alphavantage=overrides.get("alphavantage", FakeAlphaVantage()),
        fred=overrides.get("fred", FakeFred()),
        yfinance=overrides.get("yfinance", FakeYFinance()),
    )
