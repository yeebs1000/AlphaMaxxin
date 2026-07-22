"""yfinance provider — fundamentals and (US-only) option chains.

yfinance is an unofficial Yahoo scraper and breaks periodically; every
method degrades to None and skills fall back to Finnhub /stock/metric.
Imported lazily so the backend runs without the package installed.
Fundamentals are returned as a flat "raw" dict consumed by
skills/fundamentals.py — keep field names stable, tests fixture this shape.
"""
from .base import (DiskTTLCache, guard_online, to_number, TTL_FUNDAMENTALS,
                   TTL_STATEMENTS)

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

    def dividends(self, ticker: str) -> dict | None:
        """{"ttm_dps": trailing-12mo dividends per share, "ex_dividend_date":
        "YYYY-MM-DD" | None} or None when the symbol pays nothing / fetch fails."""
        return self._cache.get_or_fetch("yf_dividends", ticker, TTL_FUNDAMENTALS,
                                        lambda: self._fetch_dividends(ticker))

    def _fetch_dividends(self, ticker: str) -> dict | None:
        guard_online()
        try:
            import datetime
            import yfinance as yf
            t = yf.Ticker(ticker)
            series = t.dividends
            ttm = 0.0
            if series is not None and len(series):
                cutoff = (datetime.datetime.now(datetime.timezone.utc)
                          - datetime.timedelta(days=365))
                tail = series[series.index >= cutoff]
                ttm = float(tail.sum())
            ex_epoch = (t.info or {}).get("exDividendDate")
            ex_date = (datetime.datetime.fromtimestamp(
                ex_epoch, tz=datetime.timezone.utc).date().isoformat()
                if ex_epoch else None)
            if not ttm and not ex_date:
                return None
            return {"ttm_dps": round(ttm, 4), "ex_dividend_date": ex_date}
        except Exception:
            return None

    # Statement line items the Piotroski F-score needs, per frame.
    # yfinance row-label → our field name.
    _STMT_ROWS = {
        "income": {"Total Revenue": "revenue", "Cost Of Revenue": "cogs",
                   "Net Income": "net_income",
                   "Diluted Average Shares": "shares"},
        "balance": {"Total Assets": "total_assets", "Total Debt": "total_debt",
                    "Current Assets": "current_assets",
                    "Current Liabilities": "current_liabilities",
                    "Ordinary Shares Number": "shares_balance"},
        "cashflow": {"Operating Cash Flow": "cfo"},
    }

    def statements(self, ticker: str) -> list | None:
        """Annual statement line items for F-score math, newest year first:
        [{"period", "revenue", "cogs", "net_income", "shares", "total_assets",
          "total_debt", "current_assets", "current_liabilities", "cfo"}, ...]
        Missing items are simply absent — consumers must treat absent as
        unknown, not zero. None when yfinance has no statements (common for
        smaller HK listings — Yahoo's statement coverage thins fast off the
        main board)."""
        return self._cache.get_or_fetch("yf_statements", ticker, TTL_STATEMENTS,
                                        lambda: self._fetch_statements(ticker))

    def _fetch_statements(self, ticker: str) -> list | None:
        guard_online()
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            frames = {"income": t.income_stmt, "balance": t.balance_sheet,
                      "cashflow": t.cashflow}
        except Exception:
            return None
        years: dict = {}  # period iso date -> {field: value}
        for kind, df in frames.items():
            if df is None or getattr(df, "empty", True):
                continue
            for label, field in self._STMT_ROWS[kind].items():
                if label not in df.index:
                    continue
                for col in df.columns:
                    value = to_number(df.loc[label, col])
                    if value is None:
                        continue
                    years.setdefault(str(col.date()), {})[field] = value
        rows = []
        for period in sorted(years, reverse=True):
            row = {"period": period, **years[period]}
            # Diluted-average shares (income) preferred; balance-sheet share
            # count fills the gap when the income row is missing.
            row.setdefault("shares", row.pop("shares_balance", None))
            row.pop("shares_balance", None)
            if row.get("shares") is None:
                row.pop("shares", None)
            if len(row) > 1:
                rows.append(row)
        return rows or None

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
