"""Fundamentals snapshot — normalizes yfinance (primary) or Finnhub
/stock/metric (fallback) raw data into the structured block the
Fundamentals analyst narrates. All numbers sourced, none LLM-recalled."""
from ..data.base import to_number


def compute_fundamentals(ticker: str, yf_raw: dict | None,
                         finnhub_metrics: dict | None = None,
                         rec_trends: list | None = None,
                         akshare_raw: dict | None = None) -> dict | None:
    """FundamentalsSnapshot from whichever raw source is available, or None.
    yf_raw is the flat dict from YFinanceProvider.fundamentals();
    finnhub_metrics is the response of /stock/metric (metric=all);
    akshare_raw is the flat dict from akshare_provider.hk_fundamentals (HK
    names where yfinance is thin — same shape as yf_raw);
    rec_trends is finnhub's monthly recommendation counts (newest first)."""
    snap = None
    if yf_raw:
        snap = _from_yfinance(ticker, yf_raw)
        snap["source"] = "yfinance"
    elif finnhub_metrics:
        snap = _from_finnhub(ticker, finnhub_metrics)
        snap["source"] = "finnhub"
    elif akshare_raw:
        snap = _from_yfinance(ticker, akshare_raw)   # same flat shape
        snap["source"] = "akshare"
    if snap and rec_trends:
        snap["analyst"]["trend"] = _analyst_trend(rec_trends)
    return snap


def _analyst_trend(trends: list) -> dict | None:
    """Estimate-revision momentum from monthly recommendation counts: net buy
    score now vs ~3 months ago. Positive delta = analysts upgrading."""
    def net_buy(row):
        return ((row.get("strongBuy") or 0) + (row.get("buy") or 0)
                - (row.get("sell") or 0) - (row.get("strongSell") or 0))
    if not trends:
        return None
    latest = net_buy(trends[0])
    prior = net_buy(trends[3]) if len(trends) > 3 else None
    return {"net_buy": latest,
            "net_buy_3m_ago": prior,
            "delta_3m": (latest - prior) if prior is not None else None,
            "period": trends[0].get("period")}


def _from_yfinance(ticker: str, raw: dict) -> dict:
    """Build the structured FundamentalsSnapshot. Every numeric field is
    coerced through to_number() right here — the single point every
    consumer (quality flags, the composite signal aggregator, the
    Fundamentals analyst payload, recommendation_block) reads from, so
    fixing it here protects all of them at once instead of re-guarding
    each comparison site individually as new ones turn up."""
    n = to_number  # local alias, this function is dense with it
    return {
        "ticker": ticker,
        "name": raw.get("name"),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "market_cap": n(raw.get("market_cap")),
        "currency": raw.get("currency"),
        "price": n(raw.get("price")),
        "valuation": {
            "pe_ttm": n(raw.get("pe_ttm")),
            "fwd_pe": n(raw.get("fwd_pe")),
            "ps": n(raw.get("ps")),
            "ev_ebitda": n(raw.get("ev_ebitda")),
            "peg": n(raw.get("peg")),
        },
        "growth": {
            "rev_yoy": n(raw.get("rev_yoy")),
            "eps_yoy": n(raw.get("eps_yoy")),
        },
        "margins": {
            "gross": n(raw.get("gross_margin")),
            "operating": n(raw.get("op_margin")),
            "net": n(raw.get("net_margin")),
        },
        "balance": {
            "debt_to_equity": n(raw.get("debt_to_equity")),
            "current_ratio": n(raw.get("current_ratio")),
            "fcf": n(raw.get("fcf")),
        },
        "dividend": {
            "yield": n(raw.get("dividend_yield")),
            "payout_ratio": n(raw.get("payout_ratio")),
        },
        "analyst": {
            "target_mean": n(raw.get("target_mean")),
            "rec": raw.get("rec"),
            "count": n(raw.get("analyst_count")),
        },
        "short_interest": {
            "ratio_days": n(raw.get("short_ratio")),
            "pct_float": n(raw.get("short_pct_float")),
            "shares": n(raw.get("shares_short")),
        },
        "quality_flags": _quality_flags(raw),
    }


# Finnhub /stock/metric key → our raw-field name (subset that maps cleanly).
_FINNHUB_KEYS = {
    "peTTM": "pe_ttm",
    "psTTM": "ps",
    "revenueGrowthTTMYoy": "rev_yoy",
    "epsGrowthTTMYoy": "eps_yoy",
    "grossMarginTTM": "gross_margin",
    "operatingMarginTTM": "op_margin",
    "netProfitMarginTTM": "net_margin",
    "totalDebt/totalEquityQuarterly": "debt_to_equity",
    "currentRatioQuarterly": "current_ratio",
    "dividendYieldIndicatedAnnual": "dividend_yield",
    "payoutRatioTTM": "payout_ratio",
}


def _from_finnhub(ticker: str, metrics_response: dict) -> dict:
    metric = metrics_response.get("metric", {}) if isinstance(metrics_response, dict) else {}
    raw = {}
    for src, dst in _FINNHUB_KEYS.items():
        # Every _FINNHUB_KEYS destination is numeric — Finnhub's free tier
        # occasionally emits a sentinel string ("NM", "N/A") instead of
        # omitting the field; to_number() drops it rather than passing a
        # bad type on (same class of bug as yfinance's "Infinity" strings).
        value = to_number(metric.get(src))
        if value is None:
            continue
        raw[dst] = value
    # Finnhub reports margins/growth as percentages (e.g. 42.5); yfinance as
    # fractions (0.425) — normalize to fractions.
    for pct_field in ("rev_yoy", "eps_yoy", "gross_margin", "op_margin",
                      "net_margin", "dividend_yield", "payout_ratio"):
        if pct_field in raw:
            raw[pct_field] = raw[pct_field] / 100.0
    snap = _from_yfinance(ticker, raw)
    return snap


def f_score(years: list | None) -> dict | None:
    """Piotroski F-score from annual statement rows (newest first, shape of
    YFinanceProvider.statements). Formulas follow Piotroski (2000) as
    implemented in FinanceToolkit (MIT) — nine boolean criteria, one point
    each. Criteria whose inputs are missing return None and drop out of
    `known` instead of counting against the name (statement coverage for
    HK/Asia listings is patchy; sector gaps like no-COGS banks self-handle
    the same way). None when fewer than two years exist — every delta
    criterion needs a prior year."""
    if not years or len(years) < 2:
        return None
    y0, y1 = years[0], years[1]

    def div(num, den):
        return None if num is None or not den else num / den

    def gt(a, b):
        return None if a is None or b is None else a > b

    roa0 = div(y0.get("net_income"), y0.get("total_assets"))
    roa1 = div(y1.get("net_income"), y1.get("total_assets"))
    gm0 = div((y0["revenue"] - y0["cogs"]) if y0.get("revenue") is not None
              and y0.get("cogs") is not None else None, y0.get("revenue"))
    gm1 = div((y1["revenue"] - y1["cogs"]) if y1.get("revenue") is not None
              and y1.get("cogs") is not None else None, y1.get("revenue"))
    criteria = {
        "roa_positive": gt(roa0, 0),
        "cfo_positive": gt(y0.get("cfo"), 0),
        "roa_improving": gt(roa0, roa1),
        # Accrual quality: CFO > net income (same as CFO/TA > ROA).
        "accruals_ok": gt(y0.get("cfo"), y0.get("net_income")),
        "leverage_down": gt(div(y1.get("total_debt"), y1.get("total_assets")),
                            div(y0.get("total_debt"), y0.get("total_assets"))),
        "liquidity_up": gt(div(y0.get("current_assets"), y0.get("current_liabilities")),
                           div(y1.get("current_assets"), y1.get("current_liabilities"))),
        "no_dilution": (None if y0.get("shares") is None or y1.get("shares") is None
                        else y0["shares"] <= y1["shares"]),
        "margin_up": gt(gm0, gm1),
        "turnover_up": gt(div(y0.get("revenue"), y0.get("total_assets")),
                          div(y1.get("revenue"), y1.get("total_assets"))),
    }
    known = [v for v in criteria.values() if v is not None]
    if not known:
        return None
    return {"score": sum(known), "known": len(known), "criteria": criteria,
            "period": y0.get("period")}


def _quality_flags(raw: dict) -> list[str]:
    """Mechanical red/green flags the analyst must address, not invent.

    Reads every field through to_number() as a backstop, not just a
    convenience — the two callers already sanitize their raw dicts before
    this runs, but this function must never crash on a bad type regardless
    of *how* raw got built (a stale disk-cache entry from before a provider
    fix shipped, a future caller that forgets to sanitize, a hand-built
    fixture in a test). One coercion here is cheaper than auditing every
    upstream path forever."""
    flags = []
    pe = to_number(raw.get("pe_ttm"))
    if pe is not None and pe < 0:
        flags.append("negative trailing earnings")
    if pe is not None and pe > 60:
        flags.append(f"trailing P/E {pe:.0f} — priced for high growth")
    d_e = to_number(raw.get("debt_to_equity"))
    if d_e is not None and d_e > 200:  # yfinance reports as pct
        flags.append(f"debt/equity {d_e:.0f}% — heavily levered")
    net = to_number(raw.get("net_margin"))
    if net is not None and net < 0:
        flags.append("unprofitable (negative net margin)")
    rev = to_number(raw.get("rev_yoy"))
    if rev is not None and rev < 0:
        flags.append(f"revenue shrinking ({rev:.1%} YoY)")
    fcf = to_number(raw.get("fcf"))
    if fcf is not None and fcf < 0:
        flags.append("negative free cash flow")
    short_pct = to_number(raw.get("short_pct_float"))
    if short_pct is not None and short_pct > 0.10:
        flags.append(f"heavily shorted ({short_pct:.0%} of float) — squeeze/thesis risk")
    return flags
