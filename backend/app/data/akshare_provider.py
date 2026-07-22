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

from .base import DiskTTLCache, guard_online

_hot_cache = DiskTTLCache()
_HOT_RANK_TTL = 3600  # popularity board drifts intraday; hourly is plenty

_PERIOD = {"1d": "daily", "1wk": "weekly"}
_CCY = {"HK": "HKD", "CN": "CNY"}
# akshare hist column headers (Chinese) → our fields.
_COLS = {"open": "开盘", "close": "收盘", "high": "最高", "low": "最低",
         "volume": "成交量"}


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
                {"opens": _COLS["open"], "closes": _COLS["close"],
                 "highs": _COLS["high"], "lows": _COLS["low"],
                 "volumes": _COLS["volume"]}.items()}
    except Exception:  # noqa: BLE001 — any akshare/pandas surprise → no data
        return None


def hk_hot_rank() -> dict | None:
    """East Money's HK popularity board (guba.eastmoney.com/rank) via
    akshare's stock_hk_hot_rank_em — the venue where HK retail attention
    actually lives (X/Twitter was evaluated and rejected for this; see
    HANDOFF). Keyless, no login cookie — unlike every Xueqiu wrapper.
    → {"00700": 1, "01810": 7, ...} five-digit code → rank (1 = hottest,
    top 100 only), or None when akshare is missing or the fetch fails.
    # ponytail: column names are akshare's current Chinese headers —
    # UNVERIFIED live (house rule: no live fetches during dev). Validate
    # with one real call, same caveat as ohlcv() above."""
    ak = _ak()
    if ak is None:
        return None

    def fetch():
        guard_online()  # inside fetch so warm cache entries work offline
        try:
            df = ak.stock_hk_hot_rank_em()
            if df is None or df.empty:
                return None
            return {str(code).zfill(5): int(rank) for code, rank in
                    zip(df["代码"], df["当前排名"])}
        except Exception:  # noqa: BLE001 — any akshare/pandas surprise → no data
            return None

    return _hot_cache.get_or_fetch("akshare_hot", "hk_top100",
                                   _HOT_RANK_TTL, fetch)


def quote(ticker: str) -> dict | None:
    """Latest price + day change, derived from the last two daily bars."""
    bars = ohlcv(ticker, "1d")
    closes = (bars or {}).get("closes") or []
    if len(closes) < 2:
        return None
    last, prev = closes[-1], closes[-2]
    return {"price": last, "currency": _CCY.get(_market(ticker), "USD"),
            "change_pct": ((last - prev) / prev * 100) if prev else None}
