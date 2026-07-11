"""Supply-chain flow — sector rotation read from curated value chains.

The insight: chain STRUCTURE barely moves (ASML feeds TSMC feeds NVDA), so it
lives here as a curated data map; the SIGNAL is live momentum per tier,
computed from the same Yahoo bars the screener uses. Upstream ripping while
downstream lags = early-cycle divergence; the reverse = late-cycle. All
deterministic — the analyst narrates the computed tier table, never invents
flows. Real shipment/PO data (Bloomberg SPLC, Panjiva) is paid; this is the
free-data 80%.
# ponytail: curated tickers, revisit yearly; per-company edge weights and
# EDGAR customer-concentration auto-maintenance are the upgrade path.
"""
from .screener import candidate_snapshot

# tier → representative liquid names. upstream = equipment/materials,
# midstream = makers/integrators, downstream = consumers of the output.
CHAINS = {
    "memory_semis": {
        "label": "Memory & Semiconductors",
        "upstream": ["ASML", "AMAT", "LRCX", "KLAC", "TER"],
        "midstream": ["TSM", "005930.KS", "000660.KS", "MU", "INTC"],
        "downstream": ["NVDA", "AMD", "AAPL", "DELL", "SMCI"],
    },
    "data_centers": {
        "label": "Data Centers & AI Infra",
        "upstream": ["NVDA", "AVGO", "MRVL", "MU", "VRT"],
        "midstream": ["SMCI", "DELL", "HPE", "ANET", "CIEN"],
        "downstream": ["MSFT", "GOOGL", "AMZN", "META", "ORCL"],
    },
    "optics_networking": {
        "label": "Optics & Networking",
        "upstream": ["LITE", "COHR", "FN", "IPGP"],
        "midstream": ["CIEN", "ANET", "JNPR", "NOK"],
        "downstream": ["MSFT", "AMZN", "GOOGL", "T", "VZ"],
    },
    "ev_batteries": {
        "label": "EV & Batteries",
        "upstream": ["ALB", "SQM", "051910.KS", "006400.KS"],
        "midstream": ["1211.HK", "6752.T"],
        "downstream": ["TSLA", "GM", "F", "RIVN"],
    },
}

_TIERS = ("upstream", "midstream", "downstream")


def _tier_momentum(yahoo, tickers: list[str]) -> dict | None:
    """Median 3-month momentum across the tier's names (median — one meme
    move shouldn't drag a tier), plus coverage count."""
    moms = []
    for t in tickers:
        snap = candidate_snapshot(t, yahoo.ohlcv(t, "1d", "1y"))
        if snap and snap.get("mom_3m_pct") is not None:
            moms.append(snap["mom_3m_pct"])
    if not moms:
        return None
    moms.sort()
    mid = len(moms) // 2
    median = moms[mid] if len(moms) % 2 else (moms[mid - 1] + moms[mid]) / 2
    return {"median_mom_3m_pct": round(median, 2), "covered": len(moms),
            "of": len(tickers)}


def compute_chains(yahoo, chains: dict | None = None) -> dict:
    """{chain: {label, tiers: {tier: momentum}, divergence, read}} — the
    compact table the analyst narrates."""
    out = {}
    for key, spec in (chains or CHAINS).items():
        tiers = {tier: _tier_momentum(yahoo, spec[tier]) for tier in _TIERS}
        up, down = tiers.get("upstream"), tiers.get("downstream")
        divergence = None
        read = "insufficient data"
        if up and down:
            divergence = round(up["median_mom_3m_pct"] - down["median_mom_3m_pct"], 2)
            if divergence >= 8:
                read = "upstream leading — early-cycle pattern"
            elif divergence <= -8:
                read = "downstream leading — late-cycle / demand-pull pattern"
            else:
                read = "tiers moving together"
        out[key] = {"label": spec["label"], "tiers": tiers,
                    "upstream_minus_downstream_pct": divergence, "read": read}
    return out
