"""Broad-market screening universe — port of market_screener.py with the
fetch decoupled (provider passed in) and a momentum/RSI rank added.

US/HK/SG pull their candidate list from real index constituents
(data/index_constituents.py — S&P 500+400, Hang Seng+TECH, STI) when that
fetch succeeds; the lists below are the fallback when it doesn't (offline,
Wikipedia parse failure) — kept curated and liquid so a scan never goes
empty. JP/KR stay curated-only for now (no dynamic source wired yet).
"""
import sys

from .technicals import rsi

# Fallback candidates — see module docstring. Sector-spread: software,
# consumer, health, industrials, space (deliberately excludes trillion-
# dollar names so there's a real alternative to "buy more NVDA/AAPL").
US_CANDIDATES = [
    "RBLX", "DKNG", "ETSY", "CELH", "FIVE", "WING", "AXON", "MOD",
    "SMAR", "PCTY", "CROX", "FND", "RUN", "ONON", "DUOL", "ENPH",
    "SFM", "CAKE", "ALGM", "PLNT", "ELF", "SKX",
    "TOST", "CAVA", "BROS", "HIMS", "TMDX", "GTLB", "MNDY", "IOT",
    "GLBE", "RKLB", "WRBY", "OSCR",
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

# Regions with a dynamic (real-index) universe source, mapped to the
# index_constituents function that fetches it.
_DYNAMIC_SOURCE = {"US": "us_universe", "HK": "hk_universe", "SG": "sg_universe"}


def candidates_for(region: str) -> list[str]:
    """The region's candidate list — dynamic index constituents when that
    fetch succeeds, else the curated fallback. Never raises: any failure
    (offline, missing pandas/lxml, a changed Wikipedia table) just falls
    through to CANDIDATE_LISTS, so a scan never comes back empty."""
    source = _DYNAMIC_SOURCE.get(region)
    if source:
        try:
            from ..data import index_constituents as idx
            dynamic = getattr(idx, source)()
            if dynamic:
                return dynamic
            # Fetch succeeded but returned nothing (a normalizer rejecting
            # every cell raises no exception) — LOG it. A silent fall to the
            # tiny curated list is exactly what hid the read_html bug for days.
            print(f"[screener] {region} dynamic universe empty — using curated "
                  f"fallback ({len(CANDIDATE_LISTS.get(region, []))} names)",
                  file=sys.stderr)
        except Exception as e:  # noqa: BLE001 — dynamic universe is best-effort
            print(f"[screener] {region} dynamic universe failed "
                  f"({type(e).__name__}: {e}) — using curated fallback",
                  file=sys.stderr)
    return CANDIDATE_LISTS.get(region, [])


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


_OVERSOLD_RSI = 35   # channel cutoff — wide enough to feed gate's rsi<30 setup


def screen(yahoo, regions: list | None = None,
           max_per_market: int = _MAX_PER_MARKET) -> dict:
    """{"<REGION>": [snapshot, ...]} using the given yahoo provider (real or
    fake). Each region returns TWO channels, deduped: the top momentum
    leaders AND the most-oversold names (RSI < 35). US names with >100%
    trailing return are excluded, same rule as v1.

    The oversold channel exists because a momentum-only top-N structurally
    starves the rsi_reversion setup (the one backtested edge): oversold names
    have weak recent momentum and never make the leader list, so the gate
    would only ever see the persistent productive_trend state → the same
    names every day. RSI is already computed per candidate, so this adds zero
    fetches. Fundamentals "high" still filters junk downstream."""
    regions = regions or list(CANDIDATE_LISTS.keys())
    out = {region: [] for region in regions}
    for region in regions:
        # Bars are TTL-cached, so fetching the whole candidate list is cheap.
        snaps = []
        for ticker in candidates_for(region):
            snap = candidate_snapshot(ticker, yahoo.ohlcv(ticker, "1d", "1y"))
            if snap and (region != "US" or snap["yoy_pct"] <= _MAX_YOY_PCT_US):
                snaps.append(snap)
        leaders = sorted(snaps, key=lambda s: s["mom_3m_pct"],
                         reverse=True)[:max_per_market]
        for rank, snap in enumerate(leaders, 1):
            snap["momentum_rank"] = rank
        # Rotating channel: the most-oversold names not already in leaders.
        # NB: rsi14 can be 0.0 (fully oversold) — a truthiness check (`or 100`)
        # would wrongly exclude the MOST oversold names; test explicitly None.
        seen = {s["ticker"] for s in leaders}
        oversold = sorted((s for s in snaps
                           if s.get("rsi14") is not None
                           and s["rsi14"] < _OVERSOLD_RSI
                           and s["ticker"] not in seen),
                          key=lambda s: s["rsi14"])[:max_per_market]
        out[region] = leaders + oversold
    return out
