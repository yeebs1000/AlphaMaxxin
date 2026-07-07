"""Macro snapshot — real rates/inflation/labor/Fed-balance-sheet data from
FRED, plus market quotes (indices, FX, commodities) from Yahoo and a
mechanical per-region momentum score. Replaces the LLM-recalled numbers of
the v1 macro agents; the Macro analyst narrates this, it never invents data.
"""

# Yahoo symbols for the market side of the snapshot.
INDEX_SYMBOLS = {
    "spx": "^GSPC", "ndx": "^NDX", "vix": "^VIX",
    "hsi": "^HSI", "n225": "^N225", "kospi": "^KS11", "sti": "^STI",
}
FX_SYMBOLS = {"usdjpy": "JPY=X", "usdcny": "CNY=X", "usdkrw": "KRW=X",
              "usdsgd": "SGD=X", "dxy": "DX-Y.NYB"}
COMMODITY_SYMBOLS = {"wti": "CL=F", "gold": "GC=F", "copper": "HG=F"}

# Region → which index/fx keys matter for a region-scoped run. The first
# index/fx listed is the one used for the mechanical regional_signals score.
REGION_KEYS = {
    "US": {"indices": ["spx", "ndx", "vix"], "fx": ["dxy"]},
    "HK": {"indices": ["hsi", "vix"], "fx": ["usdcny"]},
    "JP": {"indices": ["n225", "vix"], "fx": ["usdjpy"]},
    "KR": {"indices": ["kospi", "vix"], "fx": ["usdkrw"]},
    "SG": {"indices": ["sti", "vix"], "fx": ["usdsgd"]},
}


def _latest(series: dict | None) -> float | None:
    if not series or not series.get("observations"):
        return None
    return series["observations"][-1]["value"]


def _yoy_pct(series: dict | None, periods_per_year: int = 12) -> float | None:
    """YoY % change for a monthly index series (e.g. CPI, PCE)."""
    if not series:
        return None
    obs = series.get("observations", [])
    if len(obs) < periods_per_year + 1:
        return None
    now, then = obs[-1]["value"], obs[-1 - periods_per_year]["value"]
    return ((now - then) / then) * 100 if then else None


def _change_over(series: dict | None, periods: int) -> float | None:
    """Absolute change over the last `periods` observations (e.g. Fed
    balance sheet contraction/expansion pace over ~13 weekly prints)."""
    if not series:
        return None
    obs = series.get("observations", [])
    if len(obs) < periods + 1:
        return None
    return obs[-1]["value"] - obs[-1 - periods]["value"]


def _momentum_pct(yahoo, symbol: str | None, range_: str) -> float | None:
    """% change from first to last close over `range_` (e.g. "1mo", "3mo") —
    same trailing-return calc the screener uses, applied to an index/FX pair
    instead of a stock candidate."""
    if not symbol:
        return None
    bars = yahoo.ohlcv(symbol, "1d", range_)
    closes = (bars or {}).get("closes", [])
    if len(closes) < 5 or not closes[0]:
        return None
    return ((closes[-1] - closes[0]) / closes[0]) * 100


def _regional_signal(yahoo, region: str) -> dict:
    """Mechanical -2..+2 composite score from real index/FX momentum — the
    same spirit as v1's Regional Macro Signal Table, computed instead of
    LLM-guessed. Heuristic scaling (momentum% / 8, clamped): documented, not
    a statistically fitted model — the analyst narrates what it means, it
    doesn't invent the number."""
    keys = REGION_KEYS.get(region, REGION_KEYS["US"])
    index_symbol = INDEX_SYMBOLS.get(keys["indices"][0])
    fx_symbol = FX_SYMBOLS.get(keys["fx"][0]) if keys["fx"] else None
    index_mom_3m = _momentum_pct(yahoo, index_symbol, "3mo")
    fx_mom_1m = _momentum_pct(yahoo, fx_symbol, "1mo")
    components = [c for c in (index_mom_3m, fx_mom_1m) if c is not None]
    score = round(max(-2.0, min(2.0, (sum(components) / len(components)) / 8.0)), 2) \
        if components else None
    return {"region": region, "index_momentum_3m_pct":
            round(index_mom_3m, 2) if index_mom_3m is not None else None,
            "fx_momentum_1m_pct":
            round(fx_mom_1m, 2) if fx_mom_1m is not None else None,
            "composite_score": score}


def compute_macro(fred, yahoo, regions: list | None = None) -> dict:
    """MacroSnapshot: FRED rates/inflation/labor/balance-sheet + market
    quotes + per-region momentum score. Fields are None when a source is
    unavailable — the analyst prompt requires flagging gaps, never filling
    them from memory."""
    fed_funds = _latest(fred.series("FEDFUNDS"))
    ust2y = _latest(fred.series("DGS2"))
    ust10y = _latest(fred.series("DGS10"))
    cpi_yoy = _yoy_pct(fred.series("CPIAUCSL"))
    core_cpi_yoy = _yoy_pct(fred.series("CPILFESL"))
    pce_yoy = _yoy_pct(fred.series("PCEPI"))
    unemployment = _latest(fred.series("UNRATE"))
    jobless_claims = _latest(fred.series("ICSA"))
    breakeven_10y = _latest(fred.series("T10YIE"))
    fed_balance_sheet = _latest(fred.series("WALCL"))
    fed_balance_sheet_13w_change = _change_over(fred.series("WALCL"), 13)
    # PPI: producer-side inflation (BLS Final Demand), same monthly cadence as CPI.
    ppi_yoy = _yoy_pct(fred.series("PPIFIS"))
    core_ppi_yoy = _yoy_pct(fred.series("PPICOR"))
    # NFP: PAYEMS is already reported in thousands of persons, so a 1-month
    # diff IS the monthly nonfarm payrolls change in thousands.
    nfp_change_k = _change_over(fred.series("PAYEMS"), 1)
    # Fed dot plot: the FOMC's OWN quarterly Summary of Economic Projections
    # median fed-funds path — updates only ~4x/year, not a live series.
    dot_median_next_year = _latest(fred.series("FEDTARMD"))
    dot_median_longer_run = _latest(fred.series("FEDTARMDLR"))
    market_vs_fed_gap = (round(ust2y - dot_median_next_year, 2)
                         if ust2y is not None and dot_median_next_year is not None else None)

    curve_2s10s = (ust10y - ust2y) if ust10y is not None and ust2y is not None else None

    def quotes(symbol_map: dict) -> dict:
        out = {}
        for name, symbol in symbol_map.items():
            q = yahoo.quote(symbol)
            out[name] = ({"price": q["price"], "change_pct": q.get("change_pct")}
                         if q else None)
        return out

    indices = quotes(INDEX_SYMBOLS)
    fx = quotes(FX_SYMBOLS)
    commodities = quotes(COMMODITY_SYMBOLS)

    vix_level = indices.get("vix", {}).get("price") if indices.get("vix") else None
    regime_flags = {
        "curve_inverted": curve_2s10s is not None and curve_2s10s < 0,
        "risk_off": vix_level is not None and vix_level > 25,
        "inflation_above_target": cpi_yoy is not None and cpi_yoy > 3.0,
        "fed_balance_sheet_contracting":
            fed_balance_sheet_13w_change is not None and fed_balance_sheet_13w_change < 0,
        "producer_inflation_hot": core_ppi_yoy is not None and core_ppi_yoy > 3.0,
        "payrolls_cooling": nfp_change_k is not None and nfp_change_k < 100,
    }

    region_list = regions or ["US"]
    regional_signals = [_regional_signal(yahoo, r) for r in region_list]

    return {
        "rates": {"fed_funds": fed_funds, "ust2y": ust2y, "ust10y": ust10y,
                  "curve_2s10s": curve_2s10s, "breakeven_10y": breakeven_10y},
        "inflation": {"cpi_yoy": cpi_yoy, "core_cpi_yoy": core_cpi_yoy, "pce_yoy": pce_yoy},
        "producer_prices": {"ppi_yoy": ppi_yoy, "core_ppi_yoy": core_ppi_yoy},
        "labor": {"unemployment": unemployment, "jobless_claims": jobless_claims,
                 "nonfarm_payrolls_change_k": nfp_change_k},
        "fed_balance_sheet": {"level": fed_balance_sheet,
                              "change_13w": fed_balance_sheet_13w_change},
        "fed_dot_plot": {"median_next_year": dot_median_next_year,
                        "median_longer_run": dot_median_longer_run,
                        "market_vs_fed_gap": market_vs_fed_gap},
        "indices": indices,
        "fx": fx,
        "commodities": commodities,
        "regime_flags": regime_flags,
        "regions": region_list,
        "regional_signals": regional_signals,
    }
