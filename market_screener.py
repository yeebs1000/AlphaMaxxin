"""
AlphaMaxxin — Broad Market Screening Universe
Builds a real-data candidate list for standalone market-scan presets (the
High-Conviction Stock & Options Screener, and the region-focused "Watch"/
"Signal"/"Premium" presets), so they scan the broad market instead of just
the user's own Portfolio.md holdings.

Each candidate's price and trailing-12-month return is pulled from the same
Yahoo Finance chart endpoint already used by technical_indicators.py — no
new dependency, no LLM call, no portfolio data involved.
"""
import datetime

from technical_indicators import fetch_ohlcv_yahoo

# Curated, liquid, NON-mega-cap US candidates (roughly mid/small-cap —
# deliberately excludes the trillion/hundred-billion-dollar names so the
# screener has a real alternative to "buy more NVDA/AAPL").
US_CANDIDATES = [
    "RBLX", "DKNG", "ETSY", "CELH", "FIVE", "WING", "AXON", "MOD",
    "SMAR", "PCTY", "CROX", "FND", "RUN", "ONON", "DUOL", "ENPH",
    "SFM", "CAKE", "ALGM", "PLNT", "ELF", "SKX",
]

# Liquid Singapore Exchange (SGX) names, Yahoo ".SI" suffix.
SG_CANDIDATES = [
    "D05.SI", "O39.SI", "U11.SI", "C6L.SI", "Z74.SI", "C38U.SI",
    "A17U.SI", "S68.SI", "BN4.SI", "F34.SI",
]

# Liquid Hong Kong Exchange (HKEX) names, Yahoo ".HK" suffix.
HK_CANDIDATES = [
    "9988.HK", "3690.HK", "1810.HK", "2318.HK", "0288.HK", "1211.HK",
    "9618.HK", "0006.HK", "2628.HK", "1093.HK",
]

# Liquid Tokyo Stock Exchange names, Yahoo ".T" suffix.
JP_CANDIDATES = [
    "7203.T", "6758.T", "9984.T", "8035.T", "6920.T",
    "4063.T", "9433.T", "6098.T", "8306.T", "4519.T",
]

# Liquid KOSPI/KOSDAQ names, Yahoo ".KS" suffix.
KR_CANDIDATES = [
    "005930.KS", "000660.KS", "035420.KS", "035720.KS", "051910.KS",
    "006400.KS", "207940.KS", "323410.KS", "012330.KS", "068270.KS",
]

_CANDIDATE_LISTS = {
    "US": US_CANDIDATES, "SG": SG_CANDIDATES, "HK": HK_CANDIDATES,
    "JP": JP_CANDIDATES, "KR": KR_CANDIDATES,
}

REGION_LABELS = {
    "US": "United States (non-mega-cap, trailing 12-month return <= +100%)",
    "SG": "Singapore Exchange (SGX)",
    "HK": "Hong Kong Exchange (HKEX)",
    "JP": "Japan — Tokyo Stock Exchange",
    "KR": "South Korea — KOSPI/KOSDAQ",
}

_MAX_YOY_PCT_US = 100.0  # exclude US candidates that already ran >100% YoY
_MAX_PER_MARKET = 6


def _candidate_snapshot(ticker: str) -> dict | None:
    bars = fetch_ohlcv_yahoo(ticker, interval="1d", range_="1y")
    if not bars or len(bars["closes"]) < 20:
        return None
    closes = bars["closes"]
    last_close = closes[-1]
    yoy_pct = ((last_close - closes[0]) / closes[0]) * 100 if closes[0] else 0.0
    return {"ticker": ticker, "last_close": last_close, "yoy_pct": yoy_pct}


def get_market_candidates(max_per_market: int = _MAX_PER_MARKET, regions: list = None) -> dict:
    """Returns {"<REGION>": [...]} of real snapshots, each capped to
    max_per_market. Defaults to every known region (US/SG/HK/JP/KR); pass
    e.g. regions=["JP"] to scope a region-focused preset (Sakura Signal,
    Kimchi Premium, Dragon Watch) to just that market. US candidates with
    >100% trailing 12-month price return are excluded (the user wants real
    alternatives, not names that already doubled)."""
    regions = regions or list(_CANDIDATE_LISTS.keys())
    out = {region: [] for region in regions}

    for region in regions:
        for ticker in _CANDIDATE_LISTS.get(region, []):
            snap = _candidate_snapshot(ticker)
            if snap and (region != "US" or snap["yoy_pct"] <= _MAX_YOY_PCT_US):
                out[region].append(snap)
            if len(out[region]) >= max_per_market:
                break

    return out


def format_market_screening_context(candidates: dict) -> str:
    """Renders the candidate universe into the markdown block injected into
    a market-scan agent's prompt."""
    today = datetime.date.today().strftime("%B %d, %Y")

    def _section(region: str) -> str:
        rows = candidates.get(region, [])
        label = REGION_LABELS.get(region, region)
        if not rows:
            return f"{label}: [No live data available this run]"
        lines = "\n".join(
            f"  - {r['ticker']} — Last Close: {r['last_close']:.2f} — "
            f"Trailing 12-Month Return: {r['yoy_pct']:+.1f}%"
            for r in rows
        )
        return f"{label}:\n{lines}"

    sections = "\n\n".join(_section(region) for region in candidates.keys())

    if len(candidates) > 1:
        coverage_note = (
            "Your published equity/options setups must include, if any candidate in\n"
            "  that bucket passes your conviction gates, at least 1 setup from EACH\n"
            "  region listed above. If a bucket has no candidate that clears your\n"
            "  gates, say so explicitly in that bucket instead of silently omitting it\n"
            "  — do not lower your conviction bar to force a fit."
        )
    else:
        coverage_note = (
            "This run is scoped to a single region — stay within it; do not\n"
            "  substitute candidates from other markets. If nothing here clears your\n"
            "  conviction gates, say so explicitly rather than lowering the bar."
        )

    return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BROAD MARKET SCREENING UNIVERSE (real live data, as of {today})
This is your scanning universe for THIS run — it is independent of the
user's own portfolio holdings shown above. The holdings above are shown
only so you can avoid recommending a duplicate position; do not limit
your search to them.

{sections}

COVERAGE REQUIREMENT FOR THIS RUN:
  {coverage_note}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
