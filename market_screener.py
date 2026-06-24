"""
AlphaMaxxin — Broad Market Screening Universe
Builds a real-data candidate list for the High-Conviction Stock & Options
Screener agent, so it scans the broad market instead of just the user's
own Portfolio.md holdings.

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


def get_market_candidates(max_per_market: int = _MAX_PER_MARKET) -> dict:
    """Returns {"US": [...], "SG": [...], "HK": [...]} of real snapshots,
    each capped to max_per_market. US candidates with >100% trailing 12-month
    price return are excluded (the user wants real alternatives, not names
    that already doubled)."""
    out = {"US": [], "SG": [], "HK": []}

    for ticker in US_CANDIDATES:
        snap = _candidate_snapshot(ticker)
        if snap and snap["yoy_pct"] <= _MAX_YOY_PCT_US:
            out["US"].append(snap)
        if len(out["US"]) >= max_per_market:
            break

    for ticker in SG_CANDIDATES:
        snap = _candidate_snapshot(ticker)
        if snap:
            out["SG"].append(snap)
        if len(out["SG"]) >= max_per_market:
            break

    for ticker in HK_CANDIDATES:
        snap = _candidate_snapshot(ticker)
        if snap:
            out["HK"].append(snap)
        if len(out["HK"]) >= max_per_market:
            break

    return out


def format_market_screening_context(candidates: dict) -> str:
    """Renders the candidate universe into the markdown block injected into
    the Screener agent's prompt."""
    today = datetime.date.today().strftime("%B %d, %Y")

    def _section(label: str, rows: list) -> str:
        if not rows:
            return f"{label}: [No live data available this run]"
        lines = "\n".join(
            f"  - {r['ticker']} — Last Close: {r['last_close']:.2f} — "
            f"Trailing 12-Month Return: {r['yoy_pct']:+.1f}%"
            for r in rows
        )
        return f"{label}:\n{lines}"

    return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BROAD MARKET SCREENING UNIVERSE (real live data, as of {today})
This is your scanning universe for THIS run — it is independent of the
user's own portfolio holdings shown above. The holdings above are shown
only so you can avoid recommending a duplicate position; do not limit
your search to them.

US candidates below are pre-filtered to exclude mega-cap names and any
name that already returned more than 100% over the trailing 12 months —
the user specifically wants real alternatives, not "buy more of what
already mooned."

{_section("US (non-mega-cap, YoY <= +100%)", candidates.get("US", []))}

{_section("Singapore Exchange (SGX)", candidates.get("SG", []))}

{_section("Hong Kong Exchange (HKEX)", candidates.get("HK", []))}

COVERAGE REQUIREMENT FOR THIS RUN:
  Your published equity/options setups must include, if any candidate in
  that bucket passes your conviction gates: at least 1 US setup from the
  non-mega-cap list above, at least 1 Singapore-listed setup, and at least
  1 Hong Kong-listed setup. If a bucket has no candidate that clears your
  gates, say so explicitly in that bucket instead of silently omitting it
  — do not lower your conviction bar to force a fit.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
