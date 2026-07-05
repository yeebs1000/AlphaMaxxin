"""Fundamentals snapshot — normalizes yfinance (primary) or Finnhub
/stock/metric (fallback) raw data into the structured block the
Fundamentals analyst narrates. All numbers sourced, none LLM-recalled."""


def compute_fundamentals(ticker: str, yf_raw: dict | None,
                         finnhub_metrics: dict | None = None) -> dict | None:
    """FundamentalsSnapshot from whichever raw source is available, or None.
    yf_raw is the flat dict from YFinanceProvider.fundamentals();
    finnhub_metrics is the response of /stock/metric (metric=all)."""
    if yf_raw:
        snap = _from_yfinance(ticker, yf_raw)
        snap["source"] = "yfinance"
        return snap
    if finnhub_metrics:
        snap = _from_finnhub(ticker, finnhub_metrics)
        snap["source"] = "finnhub"
        return snap
    return None


def _from_yfinance(ticker: str, raw: dict) -> dict:
    return {
        "ticker": ticker,
        "name": raw.get("name"),
        "sector": raw.get("sector"),
        "industry": raw.get("industry"),
        "market_cap": raw.get("market_cap"),
        "currency": raw.get("currency"),
        "price": raw.get("price"),
        "valuation": {
            "pe_ttm": raw.get("pe_ttm"),
            "fwd_pe": raw.get("fwd_pe"),
            "ps": raw.get("ps"),
            "ev_ebitda": raw.get("ev_ebitda"),
            "peg": raw.get("peg"),
        },
        "growth": {
            "rev_yoy": raw.get("rev_yoy"),
            "eps_yoy": raw.get("eps_yoy"),
        },
        "margins": {
            "gross": raw.get("gross_margin"),
            "operating": raw.get("op_margin"),
            "net": raw.get("net_margin"),
        },
        "balance": {
            "debt_to_equity": raw.get("debt_to_equity"),
            "current_ratio": raw.get("current_ratio"),
            "fcf": raw.get("fcf"),
        },
        "dividend": {
            "yield": raw.get("dividend_yield"),
            "payout_ratio": raw.get("payout_ratio"),
        },
        "analyst": {
            "target_mean": raw.get("target_mean"),
            "rec": raw.get("rec"),
            "count": raw.get("analyst_count"),
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
        value = metric.get(src)
        if value is not None:
            raw[dst] = value
    # Finnhub reports margins/growth as percentages (e.g. 42.5); yfinance as
    # fractions (0.425) — normalize to fractions.
    for pct_field in ("rev_yoy", "eps_yoy", "gross_margin", "op_margin",
                      "net_margin", "dividend_yield", "payout_ratio"):
        if pct_field in raw:
            raw[pct_field] = raw[pct_field] / 100.0
    snap = _from_yfinance(ticker, raw)
    return snap


def _quality_flags(raw: dict) -> list[str]:
    """Mechanical red/green flags the analyst must address, not invent."""
    flags = []
    pe = raw.get("pe_ttm")
    if pe is not None and pe < 0:
        flags.append("negative trailing earnings")
    if pe is not None and pe > 60:
        flags.append(f"trailing P/E {pe:.0f} — priced for high growth")
    d_e = raw.get("debt_to_equity")
    if d_e is not None and d_e > 200:  # yfinance reports as pct
        flags.append(f"debt/equity {d_e:.0f}% — heavily levered")
    net = raw.get("net_margin")
    if net is not None and net < 0:
        flags.append("unprofitable (negative net margin)")
    rev = raw.get("rev_yoy")
    if rev is not None and rev < 0:
        flags.append(f"revenue shrinking ({rev:.1%} YoY)")
    fcf = raw.get("fcf")
    if fcf is not None and fcf < 0:
        flags.append("negative free cash flow")
    return flags
