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

from .base import DiskTTLCache, TTL_STATEMENTS, guard_online, to_number

_hot_cache = DiskTTLCache()
_HOT_RANK_TTL = 3600  # popularity board drifts intraday; hourly is plenty
_fund_cache = DiskTTLCache()

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


# East Money HK F10 (stock_financial_hk_analysis_indicator_em) → our fields.
# Verified against live 00700/02015 output: stable English column codes (not
# the fragile Chinese line-item names of the raw report_em endpoint), values
# are percentages where noted. Currency-agnostic — everything used here is a
# ratio, so HKD-vs-CNY reporting doesn't matter.
def _hk_pct(row: dict, key: str):
    """Percentage field → fraction (13.86 → 0.1386), or None."""
    v = to_number(row.get(key))
    return v / 100.0 if v is not None else None


def _hk_raw(rows: list[dict]) -> dict | None:
    """Latest annual row → the flat 'raw' dict compute_fundamentals expects
    (same shape as yfinance's sanitize_info output). Only the fields the
    indicator table actually carries — the rest stay absent (→ None), never
    guessed."""
    if not rows:
        return None
    r = rows[0]
    raw = {
        "name": r.get("SECURITY_NAME_ABBR"),
        "currency": r.get("CURRENCY"),
        "rev_yoy": _hk_pct(r, "OPERATE_INCOME_YOY"),
        "eps_yoy": _hk_pct(r, "HOLDER_PROFIT_YOY"),   # net-profit YoY proxy
        "gross_margin": _hk_pct(r, "GROSS_PROFIT_RATIO"),
        "net_margin": _hk_pct(r, "NET_PROFIT_RATIO"),
        "current_ratio": to_number(r.get("CURRENT_RATIO")),
    }
    # True EPS YoY from consecutive basic-EPS when both are present — more
    # honest than the net-profit proxy (captures dilution).
    if len(rows) > 1:
        e0, e1 = to_number(r.get("BASIC_EPS")), to_number(rows[1].get("BASIC_EPS"))
        if e0 is not None and e1:
            raw["eps_yoy"] = e0 / e1 - 1
    return {k: v for k, v in raw.items() if v is not None} or None


def _hk_years(rows: list[dict]) -> list[dict]:
    """Indicator rows → the statement-year shape f_score() consumes, deriving
    absolutes from the ratios (assets = net_income / ROA, etc.). Missing
    inputs stay absent so f_score drops those criteria rather than failing."""
    years = []
    for r in rows:
        ni = to_number(r.get("HOLDER_PROFIT"))
        rev = to_number(r.get("OPERATE_INCOME"))
        gross = to_number(r.get("GROSS_PROFIT"))
        roa = to_number(r.get("ROA"))          # percent
        ocf_sales = to_number(r.get("OCF_SALES"))   # percent
        debt_asset = to_number(r.get("DEBT_ASSET_RATIO"))  # percent
        eps = to_number(r.get("BASIC_EPS"))
        assets = ni / (roa / 100) if (ni is not None and roa) else None
        y = {"period": str(r.get("REPORT_DATE") or "")[:10]}
        if ni is not None:
            y["net_income"] = ni
        if rev is not None:
            y["revenue"] = rev
        if rev is not None and gross is not None:
            y["cogs"] = rev - gross
        if assets is not None:
            y["total_assets"] = assets
            if debt_asset is not None:
                y["total_debt"] = debt_asset / 100 * assets
        if rev is not None and ocf_sales is not None:
            y["cfo"] = ocf_sales / 100 * rev
        if ni is not None and eps:
            y["shares"] = ni / eps
        # CURRENT_RATIO carries the liquidity delta directly; express as a
        # ratio (CA over 1) so f_score's current_ratio comparison works.
        cr = to_number(r.get("CURRENT_RATIO"))
        if cr is not None:
            y["current_assets"], y["current_liabilities"] = cr, 1.0
        if len(y) > 1:
            years.append(y)
    return years


def hk_fundamentals(ticker: str) -> dict | None:
    """HK fundamentals from East Money's F10 indicator table — the coverage
    yfinance thins out on for HK mid/small caps. Returns
    {"raw": <flat dict>, "years": [<f_score rows>]} or None. 30-day cached
    (annual data). Keyless, no login cookie.
    # ponytail: reuses f_score()'s year shape rather than a parallel HK
    # scorer — the akshare-specific knowledge is only in the row→field map."""
    ak = _ak()
    if ak is None or _market(ticker) != "HK":
        return None

    def fetch():
        guard_online()
        try:
            code = _code(ticker, "HK")
            df = ak.stock_financial_hk_analysis_indicator_em(symbol=code, indicator="年度")
            if df is None or df.empty:
                return None
            rows = sorted(df.to_dict("records"),
                          key=lambda r: str(r.get("REPORT_DATE") or ""), reverse=True)
            raw = _hk_raw(rows)
            if raw is None:
                return None
            raw["ticker"] = ticker
            return {"raw": raw, "years": _hk_years(rows)}
        except Exception:  # noqa: BLE001 — any akshare/pandas surprise → no data
            return None

    return _fund_cache.get_or_fetch("akshare_hk_fund", ticker, TTL_STATEMENTS, fetch)


def quote(ticker: str) -> dict | None:
    """Latest price + day change, derived from the last two daily bars."""
    bars = ohlcv(ticker, "1d")
    closes = (bars or {}).get("closes") or []
    if len(closes) < 2:
        return None
    last, prev = closes[-1], closes[-2]
    return {"price": last, "currency": _CCY.get(_market(ticker), "USD"),
            "change_pct": ((last - prev) / prev * 100) if prev else None}
