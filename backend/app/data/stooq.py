"""Stooq — keyless CSV fallback for US daily/weekly bars, used when Yahoo
rate-limits or yfinance is unavailable (the scanner's documented failure
mode). Fallback-resilience pattern mined from ZhuLinsen/daily_stock_analysis.

US symbols only ('AAPL' → 'aapl.us'); suffixed or numeric tickers return
None so the akshare leg keeps owning HK/CN. Last resort in live_ohlcv —
it can only add coverage, never regress the primary sources.
"""
from .base import (DiskTTLCache, TTL_OHLCV, guard_online, http_get_text,
                   to_number)

_URL = "https://stooq.com/q/d/l/?s={sym}&i={interval}"
_INTERVALS = {"1d": "d", "1wk": "w"}
_cache = DiskTTLCache()


def symbol_for(ticker: str) -> str | None:
    """'AAPL' → 'aapl.us'; anything suffixed (9988.HK, D05.SI) or numeric
    (bare HK codes) is not ours → None."""
    t = (ticker or "").strip().upper()
    if not t or "." in t or not t[0].isalpha():
        return None
    return f"{t.lower()}.us"


def ohlcv(ticker: str, interval: str = "1d", max_bars: int = 260) -> dict | None:
    """Yahoo-shaped bars dict ({"timestamps","opens","closes",...}) or None."""
    stooq_interval = _INTERVALS.get(interval)
    sym = symbol_for(ticker)
    if not stooq_interval or not sym:
        return None
    return _cache.get_or_fetch(
        "stooq_ohlcv", f"{sym}:{stooq_interval}", TTL_OHLCV,
        lambda: _fetch(sym, stooq_interval, max_bars))


def _fetch(sym: str, interval: str, max_bars: int) -> dict | None:
    guard_online()
    try:
        text = http_get_text(_URL.format(sym=sym, interval=interval))
    except Exception:
        return None
    return parse_csv(text, max_bars)


def parse_csv(text: str, max_bars: int = 260) -> dict | None:
    """Stooq daily CSV (Date,Open,High,Low,Close,Volume) → bars dict."""
    lines = (text or "").strip().splitlines()
    if len(lines) < 2 or not lines[0].startswith("Date"):
        return None  # "No data" page or an HTML error body
    out = {"timestamps": [], "opens": [], "closes": [], "highs": [],
           "lows": [], "volumes": []}
    for line in lines[1:][-max_bars:]:
        parts = line.split(",")
        if len(parts) < 5:
            continue
        o, h, low, c = (to_number(p) for p in parts[1:5])
        v = to_number(parts[5]) if len(parts) > 5 else None
        if c is None:
            continue
        out["timestamps"].append(parts[0])
        out["opens"].append(o)
        out["highs"].append(h)
        out["lows"].append(low)
        out["closes"].append(c)
        out["volumes"].append(v or 0)
    return out if out["closes"] else None
