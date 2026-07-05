"""Yahoo Finance provider: OHLCV bars, live quotes, ticker search, FX rates.

Ports of technical_indicators.fetch_ohlcv_yahoo and runner.py's
search_ticker / fetch_live_price / get_usd_per_sgd, with disk caching.
No API key required.
"""
import urllib.parse

from .base import (
    DiskTTLCache, guard_online, http_get_json, TTL_OHLCV, TTL_QUOTE,
)

# Portfolio ticker aliases → Yahoo symbols (carried over from runner.py).
SGX_TICKER_MAP = {
    "A31": {"yahoo": "A31.SI", "name": "Addvalue Technologies", "currency": "SGD"},
    "C6L": {"yahoo": "C6L.SI", "name": "Singapore Airlines", "currency": "SGD"},
    "D05": {"yahoo": "D05.SI", "name": "DBS Group Holdings", "currency": "SGD"},
}
TICKER_ALIASES = {
    "Addvalue Tech": "A31.SI",
    "SIA": "C6L.SI",
    "DBS": "D05.SI",
    "SPYM": "SPLG",
    "SPLG": "SPLG",
    "SOLS": "SOLS",
    "Solstice Advanced": "SOLS",
    "SpaceX": None,  # not publicly traded
}


class YahooProvider:
    name = "yahoo"

    def __init__(self, cache: DiskTTLCache):
        self._cache = cache

    def ohlcv(self, ticker: str, interval: str = "1d", range_: str = "1y") -> dict | None:
        """Regular-session OHLCV bars. Returns
        {"timestamps","closes","highs","lows","volumes"} (gap rows dropped) or None."""
        key = f"{ticker}:{interval}:{range_}"
        return self._cache.get_or_fetch("yahoo_ohlcv", key, TTL_OHLCV,
                                        lambda: self._fetch_ohlcv(ticker, interval, range_))

    def _fetch_ohlcv(self, ticker: str, interval: str, range_: str) -> dict | None:
        guard_online()  # outside the try — the offline tripwire must not be swallowed
        try:
            q = urllib.parse.quote(ticker)
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{q}"
                   f"?range={range_}&interval={interval}")
            data = http_get_json(url)
            result = data["chart"]["result"][0]
            timestamps = result.get("timestamp", [])
            quote = result["indicators"]["quote"][0]
            rows = [
                (t, c, h, l, v)
                for t, c, h, l, v in zip(timestamps, quote["close"], quote["high"],
                                         quote["low"], quote["volume"])
                if c is not None and h is not None and l is not None and v is not None
            ]
            if len(rows) < 5:
                return None
            ts, closes, highs, lows, volumes = (list(col) for col in zip(*rows))
            return {"timestamps": ts, "closes": closes, "highs": highs,
                    "lows": lows, "volumes": volumes}
        except Exception:
            return None

    def quote(self, symbol: str) -> dict | None:
        """Live quote from chart meta: {price, name, ticker, yahoo_symbol,
        currency, previous_close, change_pct} or None."""
        return self._cache.get_or_fetch("yahoo_quote", symbol, TTL_QUOTE,
                                        lambda: self._fetch_quote(symbol))

    def _fetch_quote(self, symbol: str) -> dict | None:
        guard_online()
        try:
            q = urllib.parse.quote(symbol)
            data = http_get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}",
                                 timeout=5)
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            if price is None:
                return None
            prev_close = meta.get("previousClose") or meta.get("chartPreviousClose") or price
            change_pct = ((price - prev_close) / prev_close) * 100 if prev_close else 0.0
            resolved_symbol = meta.get("symbol", symbol)
            return {
                "price": price,
                "name": meta.get("longName") or meta.get("shortName") or symbol,
                "ticker": resolved_symbol.replace(".SI", "").upper(),
                "yahoo_symbol": resolved_symbol,
                "currency": meta.get("currency", "USD"),
                "previous_close": prev_close,
                "change_pct": change_pct,
            }
        except Exception:
            return None

    def search(self, query: str, max_results: int = 6) -> list:
        """[{symbol, name, type}] for EQUITY/ETF matches."""
        guard_online()
        try:
            q = urllib.parse.quote(query)
            url = (f"https://query1.finance.yahoo.com/v1/finance/search"
                   f"?q={q}&quotesCount={max_results}&newsCount=0")
            data = http_get_json(url, timeout=3)
            results = []
            for quote in data.get("quotes", []):
                if quote.get("quoteType") in ("EQUITY", "ETF"):
                    results.append({
                        "symbol": quote.get("symbol", ""),
                        "name": quote.get("longname") or quote.get("shortname")
                                or quote.get("symbol", ""),
                        "type": quote.get("quoteType", "EQUITY"),
                    })
            return results[:max_results]
        except Exception:
            return []

    def fx_rate(self, ccy: str) -> float | None:
        """Units of USD per 1 unit of `ccy` (e.g. fx_rate("SGD") ≈ 0.78)."""
        if ccy == "USD":
            return 1.0
        payload = self._cache.get_or_fetch("yahoo_fx", ccy, TTL_QUOTE,
                                           lambda: self._fetch_fx(ccy))
        return payload

    def _fetch_fx(self, ccy: str) -> float | None:
        # Yahoo's "SGD=X" style symbols quote ccy-per-USD; invert for USD-per-ccy.
        guard_online()
        try:
            data = http_get_json(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ccy}=X", timeout=5)
            per_usd = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            return 1.0 / per_usd if per_usd else None
        except Exception:
            return None

    def resolve_symbol(self, query: str) -> tuple[str | None, str]:
        """Resolve a portfolio ticker / company name to (yahoo_symbol, display_name),
        using the alias maps first, then a bare-numeric HKEX rule, then the
        search API. (moomoo, when connected, is checked before Yahoo entirely
        — see data.live_quote — so this numeric-HK fallback mainly matters
        when moomoo/OpenD isn't running.)"""
        for alias, mapped in TICKER_ALIASES.items():
            if query.lower() == alias.lower():
                return mapped, query
        for sgx_code, info in SGX_TICKER_MAP.items():
            if query.lower() in (sgx_code.lower(), info["name"].lower()):
                return info["yahoo"], info["name"]
        stripped = query.strip()
        if stripped.isdigit():
            # HKEX Yahoo symbols are 4-digit, e.g. "01810" -> "1810.HK".
            return f"{int(stripped):04d}.HK", query
        results = self.search(query, max_results=1)
        if results:
            return results[0]["symbol"], results[0]["name"]
        return query.upper(), query
