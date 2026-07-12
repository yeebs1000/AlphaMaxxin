"""Alternative data — attention & demand proxies per ticker: Wikipedia
pageview momentum (everyone), iTunes app stats (consumer-app names), and
Greenhouse job-board hiring velocity (companies that use it). Curated map,
honest coverage notes; this is attention data, not shipment data — the lens
prompt frames it that way.
# ponytail: map curated by hand. Google Trends deliberately excluded (see
# data/altdata.py).
"""
from ..data import altdata
from ..data.base import OfflineError


def _safe(fn, arg):
    """Provider call that degrades to None under the offline tripwire —
    an optional lens's missing data, same contract as order_book."""
    try:
        return fn(arg)
    except OfflineError:
        return None

ALT_SOURCES = {
    "MSFT": {"wiki": "Microsoft"},
    "AAPL": {"wiki": "Apple Inc."},
    "GOOGL": {"wiki": "Google"},
    "AMZN": {"wiki": "Amazon (company)"},
    "META": {"wiki": "Meta Platforms"},
    "NVDA": {"wiki": "Nvidia"},
    "TSLA": {"wiki": "Tesla, Inc."},
    "GRAB": {"wiki": "Grab Holdings", "itunes_app": 647268330},
    "DUOL": {"wiki": "Duolingo", "itunes_app": 570060128,
             "greenhouse": "duolingo"},
    "RBLX": {"wiki": "Roblox", "itunes_app": 431946152,
             "greenhouse": "roblox"},
    "9988.HK": {"wiki": "Alibaba Group"},
    "1810.HK": {"wiki": "Xiaomi"},
    "C6L.SI": {"wiki": "Singapore Airlines"},
    "SMCI": {"wiki": "Supermicro"},
    "TEM": {"wiki": "Tempus AI"},
}


def collect(tickers: list[str], sources: dict | None = None) -> dict:
    """{by_ticker: {ticker: {wiki_views, app, jobs}}, not_covered: [...]}."""
    sources = sources or ALT_SOURCES
    by_ticker, not_covered = {}, []
    for t in tickers:
        spec = sources.get(t)
        if not spec:
            not_covered.append(t)
            continue
        entry = {}
        if spec.get("wiki"):
            entry["wiki_views"] = _safe(altdata.wiki_pageviews, spec["wiki"])
        if spec.get("itunes_app"):
            entry["app"] = _safe(altdata.itunes_app, spec["itunes_app"])
        if spec.get("greenhouse"):
            entry["jobs"] = _safe(altdata.greenhouse_jobs, spec["greenhouse"])
        if any(entry.values()):
            by_ticker[t] = entry
        else:
            not_covered.append(t)
    return {"by_ticker": by_ticker, "not_covered": not_covered}
