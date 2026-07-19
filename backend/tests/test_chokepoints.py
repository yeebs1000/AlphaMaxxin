"""Chokepoint screener: mechanical checks, unknown-data handling, ranking."""
from app.skills import chokepoints


def _fund(cap=2e9, rev=0.4, delta=5, short=0.05, flags=None):
    return {"market_cap": cap, "growth": {"rev_yoy": rev},
            "analyst": {"trend": {"delta_3m": delta}},
            "short_interest": {"pct_float": short},
            "quality_flags": flags or []}


def test_score_all_checks_pass():
    r = chokepoints.score_chokepoint("AXTI", chokepoints.CHOKEPOINTS["AXTI"], _fund())
    assert r["score"] == 100 and r["checks_known"] == 5
    assert r["phase"] == "light_sources"


def test_score_damped_by_traps():
    crowded = chokepoints.score_chokepoint(
        "AAOI", chokepoints.CHOKEPOINTS["AAOI"], _fund(short=0.30))
    assert crowded["checks"]["not_crowded_short"] is False
    red = chokepoints.score_chokepoint(
        "AAOI", chokepoints.CHOKEPOINTS["AAOI"],
        _fund(flags=["distress combo: negative FCF + unprofitable + heavily levered"]))
    assert red["checks"]["no_red_lines"] is False
    big = chokepoints.score_chokepoint(
        "COHR", chokepoints.CHOKEPOINTS["COHR"], _fund(cap=20e9))
    assert big["checks"]["asymmetry_smallcap"] is False


def test_unknown_data_shrinks_denominator_not_score():
    r = chokepoints.score_chokepoint(
        "SIVE", chokepoints.CHOKEPOINTS["SIVE"],
        {"market_cap": None, "growth": {}, "analyst": {}, "short_interest": {},
         "quality_flags": []})
    # Only the two data-free checks remain known (short: unknown counts pass).
    assert r["checks_known"] == 2 and r["score"] == 100


def test_screen_ranks_and_reports_uncovered():
    fund_by_ticker = {t: _fund() for t in chokepoints.CHOKEPOINTS}
    fund_by_ticker["AXTI"] = _fund(short=0.3, delta=-2)   # worse score
    fund_by_ticker["FN"] = None                            # no data at all
    out = chokepoints.screen(None, fundamentals_fn=lambda t: fund_by_ticker[t])
    assert out["candidates"][0]["score"] >= out["candidates"][-1]["score"]
    axti = next(c for c in out["candidates"] if c["ticker"] == "AXTI")
    assert axti["score"] < 100
    # FN with zero data: score None → uncovered... unless data-free checks
    # keep it scored; verify it's consistently placed one way, never dropped.
    assert (any(c["ticker"] == "FN" for c in out["candidates"])
            or "FN" in out["uncovered"])
    assert out["universe_size"] == len(chokepoints.CHOKEPOINTS)
    assert "self-reported" in out["methodology"]
