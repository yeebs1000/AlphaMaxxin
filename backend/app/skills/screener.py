"""Broad-market screening universe — port of market_screener.py with the
fetch decoupled (provider passed in) and a momentum/RSI rank added.
"""
from .technicals import rsi

# Curated, liquid, NON-mega-cap US candidates (deliberately excludes the
# trillion-dollar names so the screener has a real alternative to "buy more
# NVDA/AAPL").
US_CANDIDATES = [
    "RBLX", "DKNG", "ETSY", "CELH", "FIVE", "WING", "AXON", "MOD",
    "SMAR", "PCTY", "CROX", "FND", "RUN", "ONON", "DUOL", "ENPH",
    "SFM", "CAKE", "ALGM", "PLNT", "ELF", "SKX",
]
SG_CANDIDATES = [
    "D05.SI", "O39.SI", "U11.SI", "C6L.SI", "Z74.SI", "C38U.SI",
    "A17U.SI", "S68.SI", "BN4.SI", "F34.SI",
]
# Liquid HKEX names across sectors — internet/tech, semis, financials,
# EV/auto, consumer, healthcare, property, energy/telco, industrials.
HK_CANDIDATES = [
    "0700.HK", "9988.HK", "3690.HK", "9618.HK", "9999.HK", "1024.HK",
    "9961.HK", "1810.HK", "0981.HK", "2382.HK",
    "0005.HK", "1299.HK", "2318.HK", "3968.HK", "0388.HK", "2628.HK",
    "1211.HK", "0175.HK", "2015.HK", "9868.HK",
    "2020.HK", "2331.HK", "0291.HK", "9633.HK", "0288.HK",
    "1093.HK", "1177.HK", "2269.HK",
    "0016.HK", "1109.HK", "0006.HK", "0883.HK", "0941.HK",
    "0669.HK", "0968.HK",
]
JP_CANDIDATES = [
    "7203.T", "6758.T", "9984.T", "8035.T", "6920.T",
    "4063.T", "9433.T", "6098.T", "8306.T", "4519.T",
]
KR_CANDIDATES = [
    "005930.KS", "000660.KS", "035420.KS", "035720.KS", "051910.KS",
    "006400.KS", "207940.KS", "323410.KS", "012330.KS", "068270.KS",
]

CANDIDATE_LISTS = {
    "US": US_CANDIDATES, "SG": SG_CANDIDATES, "HK": HK_CANDIDATES,
    "JP": JP_CANDIDATES, "KR": KR_CANDIDATES,
}

_MAX_YOY_PCT_US = 100.0  # exclude US names that already ran >100% YoY
_MAX_PER_MARKET = 6


def candidate_snapshot(ticker: str, bars: dict | None) -> dict | None:
    """One candidate row from pre-fetched daily bars: last close, trailing
    12-month return, 3-month momentum, RSI."""
    if not bars or len(bars.get("closes", [])) < 20:
        return None
    closes = bars["closes"]
    last_close = closes[-1]
    yoy_pct = ((last_close - closes[0]) / closes[0]) * 100 if closes[0] else 0.0
    lookback_3m = min(63, len(closes) - 1)  # ~63 trading days
    base_3m = closes[-lookback_3m - 1]
    mom_3m_pct = ((last_close - base_3m) / base_3m) * 100 if base_3m else 0.0
    return {
        "ticker": ticker,
        "last_close": last_close,
        "yoy_pct": yoy_pct,
        "mom_3m_pct": mom_3m_pct,
        "rsi14": rsi(closes),
    }


def screen(yahoo, regions: list | None = None,
           max_per_market: int = _MAX_PER_MARKET) -> dict:
    """{"<REGION>": [snapshot, ...]} using the given yahoo provider (real or
    fake), each region capped and ranked by 3-month momentum. US names with
    >100% trailing return are excluded, same rule as v1."""
    regions = regions or list(CANDIDATE_LISTS.keys())
    out = {region: [] for region in regions}
    for region in regions:
        # Rank the whole candidate list, THEN cap — capping before ranking
        # (the old behavior) made "top N by momentum" actually mean "first N
        # in list order". Bars are TTL-cached, so the wider fetch is cheap.
        for ticker in CANDIDATE_LISTS.get(region, []):
            snap = candidate_snapshot(ticker, yahoo.ohlcv(ticker, "1d", "1y"))
            if snap and (region != "US" or snap["yoy_pct"] <= _MAX_YOY_PCT_US):
                out[region].append(snap)
        out[region].sort(key=lambda s: s["mom_3m_pct"], reverse=True)
        del out[region][max_per_market:]
        for rank, snap in enumerate(out[region], 1):
            snap["momentum_rank"] = rank
    return out
