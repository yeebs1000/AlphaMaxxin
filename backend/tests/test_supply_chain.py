"""Supply-chain flow: tier medians, divergence reads, graceful gaps."""
from app.skills import supply_chain
from .fakes import FakeYahoo


def _bars(start, end, n=260):
    closes = [start + (end - start) * i / (n - 1) for i in range(n)]
    return {"closes": closes, "highs": [c + 1 for c in closes],
            "lows": [c - 1 for c in closes], "volumes": [1000] * n}


CHAIN = {"test": {"label": "Test Chain",
                  "upstream": ["UP1", "UP2", "UP3"],
                  "midstream": ["MID"],
                  "downstream": ["DN1", "DN2"]}}


def test_divergence_upstream_leading():
    yahoo = FakeYahoo(ohlcv_data={
        # ~3mo momentum ≈ last 63 bars; linear ramps give strong/weak moves.
        "UP1": _bars(100, 160), "UP2": _bars(100, 158), "UP3": _bars(100, 162),
        "MID": _bars(100, 110),
        "DN1": _bars(100, 101), "DN2": _bars(100, 102)})
    out = supply_chain.compute_chains(yahoo, chains=CHAIN)["test"]
    up = out["tiers"]["upstream"]
    assert up["covered"] == 3 and up["median_mom_3m_pct"] > 0
    assert out["upstream_minus_downstream_pct"] >= 8
    assert "early-cycle" in out["read"]


def test_median_resists_one_outlier():
    yahoo = FakeYahoo(ohlcv_data={
        "UP1": _bars(100, 101), "UP2": _bars(100, 102), "UP3": _bars(100, 400),
        "DN1": _bars(100, 101), "DN2": _bars(100, 101)})
    out = supply_chain.compute_chains(yahoo, chains=CHAIN)["test"]
    # Median of (~small, ~small, huge) stays small → tiers read as together.
    assert out["read"] == "tiers moving together"


def test_missing_data_degrades():
    out = supply_chain.compute_chains(FakeYahoo(), chains=CHAIN)["test"]
    assert out["tiers"]["upstream"] is None
    assert out["upstream_minus_downstream_pct"] is None
    assert out["read"] == "insufficient data"


def test_default_chains_shape():
    for spec in supply_chain.CHAINS.values():
        assert set(spec) == {"label", "upstream", "midstream", "downstream"}
        assert all(spec[t] for t in ("upstream", "midstream", "downstream"))
