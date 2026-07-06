"""Market Review — a deterministic daily backdrop: per-region index level +
day move, breadth (advancers/decliners across our tracked liquid universe),
and whether each market is open. All computed from Yahoo quotes; the macro
analyst narrates it, it never invents the numbers.

Breadth is measured over the screener's curated per-region candidate lists —
a representative liquid basket, NOT the whole exchange — so it's labelled
`universe_size` for honesty.
"""
from .. import market_calendar as cal
from .macro import INDEX_SYMBOLS, REGION_KEYS
from .screener import CANDIDATE_LISTS

_ALL_REGIONS = ["US", "SG", "HK", "JP", "KR"]


def _breadth(yahoo, tickers: list[str]) -> dict:
    """Advancers/decliners from each name's day change_pct."""
    adv = dec = flat = 0
    changes = []
    for t in tickers:
        q = yahoo.quote(t)
        chg = (q or {}).get("change_pct")
        if chg is None:
            continue
        changes.append(chg)
        if chg > 0:
            adv += 1
        elif chg < 0:
            dec += 1
        else:
            flat += 1
    covered = adv + dec + flat
    return {
        "advancers": adv, "decliners": dec, "unchanged": flat,
        "universe_size": covered,
        "advance_decline_ratio": round(adv / dec, 2) if dec else (float(adv) if adv else None),
        "avg_change_pct": round(sum(changes) / len(changes), 2) if changes else None,
    }


def compute_market_review(yahoo, regions: list | None = None) -> dict:
    """{region: {index, index_change_pct, market_status, breadth}} for each
    region. Missing sources come back as None — the analyst flags gaps."""
    out = {}
    for region in (regions or _ALL_REGIONS):
        index_symbol = INDEX_SYMBOLS.get(REGION_KEYS.get(region, {}).get("indices", [None])[0])
        q = yahoo.quote(index_symbol) if index_symbol else None
        out[region] = {
            "index_symbol": index_symbol,
            "index_level": (q or {}).get("price"),
            "index_change_pct": (q or {}).get("change_pct"),
            "market_status": cal.status(region),
            "breadth": _breadth(yahoo, CANDIDATE_LISTS.get(region, [])),
        }
    return out
