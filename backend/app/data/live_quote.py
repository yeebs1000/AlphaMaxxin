"""Live quote resolution — prefers the moomoo OpenD gateway (if connected)
over Yahoo Finance, matching v1's fetch_live_price() preference order.

This matters most for HK/CN-listed tickers: moomoo's `_make_code` already
knows how to build a correct code from a bare numeric ticker (e.g. "01810"
-> "HK.01810"), while Yahoo has no general rule for that and only resolves
tickers it has an explicit alias for or that its fuzzy search happens to
match. When the user's own live gateway is connected it's the authoritative,
more complete source; Yahoo remains the fallback when it isn't.

moomoo_client's functions raise OfflineError under ALPHAMAXXIN_OFFLINE=1 (the
same tripwire the data providers use) — treated here the same as "moomoo
unavailable", so the offline test suite falls through to the (faked) Yahoo
path instead of erroring.
"""
from .base import OfflineError


def live_quote(ticker: str, yahoo) -> dict | None:
    try:
        from ..brokers.moomoo_client import get_moomoo_quote, MOOMOO_AVAILABLE
        if MOOMOO_AVAILABLE:
            quote = get_moomoo_quote(ticker)
            if quote:
                return quote
    except (ImportError, OfflineError):
        pass
    symbol, _ = yahoo.resolve_symbol(ticker)
    q = yahoo.quote(symbol) if symbol else None
    return q if q else _akshare_quote(ticker)


def _akshare_quote(ticker: str) -> dict | None:
    """Last resort for HK/CN tickers when moomoo is down and Yahoo has nothing."""
    try:
        from . import akshare_provider as aks
        return aks.quote(ticker) if aks.available() else None
    except (ImportError, OfflineError):
        return None


def _akshare_ohlcv(ticker: str, interval: str) -> dict | None:
    try:
        from . import akshare_provider as aks
        return aks.ohlcv(ticker, interval) if aks.available() else None
    except (ImportError, OfflineError):
        return None


_MOOMOO_KTYPE = {"1d": "K_DAY", "1wk": "K_WEEK"}


def live_ohlcv(ticker: str, yahoo, interval: str = "1d", range_: str = "1y") -> dict | None:
    """Same preference order as live_quote, for historical bars. moomoo
    K-line rows are adapted into the {"closes","highs","lows","volumes"}
    shape every skill expects."""
    ktype = _MOOMOO_KTYPE.get(interval)
    if ktype:
        try:
            from ..brokers.moomoo_client import get_moomoo_kline, MOOMOO_AVAILABLE
            if MOOMOO_AVAILABLE:
                rows = get_moomoo_kline(ticker, ktype=ktype)
                if rows:
                    return {"closes": [r["close"] for r in rows],
                            "highs": [r["high"] for r in rows],
                            "lows": [r["low"] for r in rows],
                            "volumes": [r["volume"] for r in rows]}
        except (ImportError, OfflineError):
            pass
    symbol, _ = yahoo.resolve_symbol(ticker)
    bars = yahoo.ohlcv(symbol, interval, range_) if symbol else None
    return bars if bars else _akshare_ohlcv(ticker, interval)
