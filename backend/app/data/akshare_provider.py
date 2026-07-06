"""akshare — keyless fallback for Hong Kong and China A-share bars/quotes,
where Yahoo is weak and the moomoo gateway isn't connected. Imported by
live_quote/live_ohlcv as a LAST resort (after moomoo and Yahoo), so it can only
add coverage, never regress the primary sources.

akshare returns pandas DataFrames whose exact columns can shift between
versions; every fetch is wrapped so any parsing surprise degrades to "no data"
rather than crashing a report.
# ponytail: the DataFrame column names below are akshare's current Chinese
# headers — validate with one real online fetch after `pip install akshare`.
# Offline tests cover symbol mapping + fallback routing, not the live parse.
"""
from functools import lru_cache

from .base import guard_online

_PERIOD = {"1d": "daily", "1wk": "weekly"}
_CCY = {"HK": "HKD", "CN": "CNY"}
# akshare hist column headers (Chinese) → our fields.
_COLS = {"close": "收盘", "high": "最高", "low": "最低", "volume": "成交量"}


@lru_cache(maxsize=1)
def _ak():
    """The akshare module, or None if it isn't installed. Lazy + cached so the
    heavy import only happens if a fallback is actually attempted."""
    try:
        import akshare
        return akshare
    except ImportError:
        return None


def available() -> bool:
    return _ak() is not None


def _market(ticker: str) -> str:
    from ..market_calendar import market_of_ticker
    return market_of_ticker(ticker)


def _code(ticker: str, market: str) -> str:
    """'9988.HK' → '09988' (HK wants 5-digit zero-padded); '600519.SS' →
    '600519' (A-share wants the bare number)."""
    base = ticker.split(".")[0]
    return base.zfill(5) if market == "HK" else base


def ohlcv(ticker: str, interval: str = "1d", range_: str = "1y") -> dict | None:
    """{closes,highs,lows,volumes} for an HK/CN ticker, or None. `range_` is
    ignored — akshare returns full history and callers use what they need."""
    ak = _ak()
    market = _market(ticker)
    period = _PERIOD.get(interval)
    if ak is None or period is None or market not in ("HK", "CN"):
        return None
    guard_online()  # outside the try so the offline tripwire propagates
    try:
        code = _code(ticker, market)
        fn = ak.stock_hk_hist if market == "HK" else ak.stock_zh_a_hist
        df = fn(symbol=code, period=period, adjust="qfq")
        if df is None or df.empty:
            return None
        return {name: df[col].astype(float).tolist() for name, col in
                {"closes": _COLS["close"], "highs": _COLS["high"],
                 "lows": _COLS["low"], "volumes": _COLS["volume"]}.items()}
    except Exception:  # noqa: BLE001 — any akshare/pandas surprise → no data
        return None


def quote(ticker: str) -> dict | None:
    """Latest price + day change, derived from the last two daily bars."""
    bars = ohlcv(ticker, "1d")
    closes = (bars or {}).get("closes") or []
    if len(closes) < 2:
        return None
    last, prev = closes[-1], closes[-2]
    return {"price": last, "currency": _CCY.get(_market(ticker), "USD"),
            "change_pct": ((last - prev) / prev * 100) if prev else None}
