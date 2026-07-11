"""yfinance provider — fundamentals and (US-only) option chains.

yfinance is an unofficial Yahoo scraper and breaks periodically; every
method degrades to None and skills fall back to Finnhub /stock/metric.
Imported lazily so the backend runs without the package installed.
Fundamentals are returned as a flat "raw" dict consumed by
skills/fundamentals.py — keep field names stable, tests fixture this shape.
"""
from .base import DiskTTLCache, guard_online, to_number, TTL_FUNDAMENTALS

# .info keys we extract — single source of truth for the raw shape.
_INFO_FIELDS = {
    "trailingPE": "pe_ttm",
    "forwardPE": "fwd_pe",
    "priceToSalesTrailing12Months": "ps",
    "enterpriseToEbitda": "ev_ebitda",
    "pegRatio": "peg",
    "revenueGrowth": "rev_yoy",
    "earningsGrowth": "eps_yoy",
    "grossMargins": "gross_margin",
    "operatingMargins": "op_margin",
    "profitMargins": "net_margin",
    "debtToEquity": "debt_to_equity",
    "currentRatio": "current_ratio",
    "freeCashflow": "fcf",
    "dividendYield": "dividend_yield",
    "payoutRatio": "payout_ratio",
    "targetMeanPrice": "target_mean",
    "recommendationKey": "rec",
    "numberOfAnalystOpinions": "analyst_count",
    "shortRatio": "short_ratio",
    "shortPercentOfFloat": "short_pct_float",
    "sharesShort": "shares_short",
    "sector": "sector",
    "industry": "industry",
    "marketCap": "market_cap",
    "shortName": "name",
    "currency": "currency",
    "currentPrice": "price",
}

# Fields that must be numeric downstream (skills/fundamentals.py compares
# them with < / >). yfinance's .info dict occasionally serializes an
# undefined ratio (e.g. P/E with negative trailing earnings) as the
# string "Infinity" instead of a numeric type — sanitize at the boundary
# so a string never reaches a numeric comparison further down.
_NUMERIC_FIELDS = {
    "pe_ttm", "fwd_pe", "ps", "ev_ebitda", "peg", "rev_yoy", "eps_yoy",
    "gross_margin", "op_margin", "net_margin", "debt_to_equity",
    "current_ratio", "fcf", "dividend_yield", "payout_ratio",
    "target_mean", "analyst_count", "market_cap", "price",
    "short_ratio", "short_pct_float", "shares_short",
}


def sanitize_info(ticker: str, info: dict) -> dict | None:
    """Extract _INFO_FIELDS from a raw yfinance .info dict, coercing every
    numeric field through to_number() — yfinance's most common failure mode
    is the string "Infinity" for an undefined ratio (e.g. trailing P/E with
    negative earnings), which becomes None rather than a crash-in-waiting."""
    raw = {"ticker": ticker}
    for src, dst in _INFO_FIELDS.items():
        value = info.get(src)
        if value is None:
            continue
        if dst in _NUMERIC_FIELDS:
            value = to_number(value)
            if value is None:
                continue
        raw[dst] = value
    return raw if len(raw) > 1 else None


class YFinanceProvider:
    name = "yfinance"

    def __init__(self, cache: DiskTTLCache):
        self._cache = cache

    @property
    def available(self) -> bool:
        try:
            import yfinance  # noqa: F401
            return True
        except ImportError:
            return False

    def fundamentals(self, ticker: str) -> dict | None:
        """Flat raw fundamentals dict (keys = _INFO_FIELDS values) or None."""
        return self._cache.get_or_fetch("yf_fundamentals", ticker, TTL_FUNDAMENTALS,
                                        lambda: self._fetch_fundamentals(ticker))

    def _fetch_fundamentals(self, ticker: str) -> dict | None:
        guard_online()
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
        except Exception:
            return None
        if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
            # yfinance returns a near-empty dict for unknown symbols
            if not any(k in info for k in _INFO_FIELDS):
                return None
        return sanitize_info(ticker, info)

    def option_chain(self, ticker: str) -> dict | None:
        """Nearest-expiry option chain (US tickers only):
        {"expiry", "spot", "calls": [{strike, last, bid, ask, iv, oi}], "puts": [...]}"""
        return self._cache.get_or_fetch("yf_options", ticker, TTL_FUNDAMENTALS,
                                        lambda: self._fetch_option_chain(ticker))

    def _fetch_option_chain(self, ticker: str) -> dict | None:
        guard_online()
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            expiries = t.options
            if not expiries:
                return None
            expiry = expiries[0]
            chain = t.option_chain(expiry)
            spot = (t.fast_info or {}).get("last_price")

            def rows(df):
                out = []
                for _, r in df.iterrows():
                    out.append({
                        "strike": float(r.get("strike", 0)),
                        "last": float(r.get("lastPrice", 0) or 0),
                        "bid": float(r.get("bid", 0) or 0),
                        "ask": float(r.get("ask", 0) or 0),
                        "iv": float(r.get("impliedVolatility", 0) or 0),
                        "oi": int(r.get("openInterest", 0) or 0),
                    })
                return out

            return {"expiry": expiry, "spot": spot,
                    "calls": rows(chain.calls), "puts": rows(chain.puts)}
        except Exception:
            return None
