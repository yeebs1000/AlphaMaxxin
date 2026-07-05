"""Macro snapshot — real rates/inflation/labor from FRED plus market quotes
(indices, FX, commodities) from Yahoo. Replaces the LLM-recalled numbers of
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

# Region → which index/fx keys matter for a region-scoped run.
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
    """YoY % change for a monthly index series (e.g. CPI)."""
    if not series:
        return None
    obs = series.get("observations", [])
    if len(obs) < periods_per_year + 1:
        return None
    now, then = obs[-1]["value"], obs[-1 - periods_per_year]["value"]
    return ((now - then) / then) * 100 if then else None


def compute_macro(fred, yahoo, regions: list | None = None) -> dict:
    """MacroSnapshot: FRED rates/inflation/labor + market quotes. Fields are
    None when a source is unavailable — the analyst prompt requires flagging
    gaps, never filling them from memory."""
    fed_funds = _latest(fred.series("FEDFUNDS"))
    ust2y = _latest(fred.series("DGS2"))
    ust10y = _latest(fred.series("DGS10"))
    cpi_yoy = _yoy_pct(fred.series("CPIAUCSL"))
    core_cpi_yoy = _yoy_pct(fred.series("CPILFESL"))
    unemployment = _latest(fred.series("UNRATE"))

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
    }

    return {
        "rates": {"fed_funds": fed_funds, "ust2y": ust2y, "ust10y": ust10y,
                  "curve_2s10s": curve_2s10s},
        "inflation": {"cpi_yoy": cpi_yoy, "core_cpi_yoy": core_cpi_yoy},
        "labor": {"unemployment": unemployment},
        "indices": indices,
        "fx": fx,
        "commodities": commodities,
        "regime_flags": regime_flags,
        "regions": regions or ["US"],
    }
