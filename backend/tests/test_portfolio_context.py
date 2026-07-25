"""Portfolio context: weekly beta, crowding, overlap — pure, offline."""
import numpy as np

from app.skills import portfolio_context as pc


def _series(n, scale=1.0, seed=0, drift=0.0):
    rng = np.random.default_rng(seed)
    return list(rng.normal(drift, 0.01, n) * scale)


def test_weekly_compounds_five_bars():
    daily = [0.01] * 10
    w = pc.weekly(daily)
    assert len(w) == 2
    assert abs(w[0] - (1.01 ** 5 - 1)) < 1e-12


def test_weekly_drops_the_ragged_tail():
    assert len(pc.weekly([0.0] * 12)) == 2      # 12 bars -> 2 whole weeks


def test_beta_of_the_benchmark_against_itself_is_one():
    bench = _series(400, seed=1)
    assert pc.beta(bench, bench) == 1.0


def test_beta_scales_with_amplitude():
    bench = _series(400, seed=2)
    levered = [2 * r for r in bench]
    assert pc.beta(levered, bench) == 2.0


def test_beta_refuses_a_short_sample():
    """Returning a beta off 8 weeks would be false precision."""
    short = _series(40, seed=3)          # 8 weeks
    assert pc.beta(short, short) is None


def test_correlation_and_its_floor():
    a = _series(300, seed=4)
    assert pc.correlation(a, a) == 1.0
    assert pc.correlation(a, [-x for x in a]) == -1.0
    assert pc.correlation(_series(10), _series(10)) is None   # too few bars


def test_candidate_context_reports_crowding_and_overlap():
    bench = _series(400, seed=5)
    tech = [1.2 * r for r in bench]
    weights = {"SMCI": 0.20, "MSFT": 0.20, "KHC": 0.10}
    sectors = {"SMCI": "Technology", "MSFT": "Technology", "KHC": "Consumer Defensive"}
    returns = {"SMCI": tech, "MSFT": tech, "KHC": _series(400, seed=9), "NVDA": tech}
    ctx = pc.candidate_context("NVDA", weights, sectors, returns, bench,
                               add_weight=0.10, candidate_sector="Technology")
    # Adding a 4th tech name to a book already 80% tech (0.4 of 0.5) crowds it.
    assert ctx["sector_weight_after"] > ctx["sector_weight"]
    assert ctx["crowded"] is True
    # It is perfectly correlated with two existing holdings — must be flagged.
    assert {o["ticker"] for o in ctx["overlaps"]} == {"SMCI", "MSFT"}
    assert ctx["overlaps"][0]["corr"] == 1.0
    # Beta is reported for the name and the book, before and after.
    assert ctx["beta"] == 1.2
    assert ctx["book_beta"] is not None and ctx["book_beta_after"] is not None


def test_already_held_is_flagged_not_reported_as_self_correlation():
    """Portfolio.md carries local tickers (D05) while the scan emits Yahoo
    symbols (D05.SI). A plain equality test misses the match and the name
    reports 'corr 1.0 w/ D05' against itself instead of 'already held'."""
    bench = _series(400, seed=6)
    r = [1.1 * x for x in bench]
    ctx = pc.candidate_context("D05.SI", {"D05": 0.18, "MSFT": 0.27},
                               {"D05": "Financial Services"},
                               {"D05": r, "D05.SI": r, "MSFT": _series(400, seed=7)},
                               bench, add_weight=0.05)
    assert ctx["already_held"] is True
    assert ctx["held_weight"] == 0.18
    assert all(o["ticker"] != "D05" for o in ctx["overlaps"])   # no self-overlap
    assert "already held (18%)" in pc.context_line(ctx)
    # A genuinely new name is not flagged.
    fresh = pc.candidate_context("O39.SI", {"D05": 0.18}, {}, {"O39.SI": r}, bench)
    assert fresh["already_held"] is False


def test_candidate_context_degrades_to_none_without_data():
    ctx = pc.candidate_context("XYZ", {"AAA": 0.5}, {}, {}, None)
    assert ctx["beta"] is None and ctx["book_beta"] is None
    assert ctx["overlaps"] == []
    assert pc.context_line(ctx) is None      # nothing known -> no line


def test_context_line_is_compact():
    ctx = {"beta": 1.3, "book_beta": 0.95, "book_beta_after": 1.02,
           "sector": "Technology", "sector_weight": 0.30,
           "sector_weight_after": 0.38, "crowded": True,
           "overlaps": [{"ticker": "SMCI", "corr": 0.85}]}
    line = pc.context_line(ctx)
    assert "beta 1.3" in line and "book 0.95→1.02" in line
    assert "Technology 30%→38%" in line and "⚠" in line
    assert "corr 0.85 w/ SMCI" in line
