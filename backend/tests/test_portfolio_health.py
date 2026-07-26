"""Portfolio health: dimension scoring and recommendation rules. Pure/offline."""
from app.skills import portfolio_health as ph


def _pos(ticker, weight, sector="Technology", sleeve="core", fund_score=80,
         beta=1.0, stage="compounder"):
    return {"ticker": ticker, "weight": weight, "sector": sector,
            "sleeve": sleeve, "fund_score": fund_score, "beta": beta,
            "stage": stage}


def _balanced():
    """A deliberately well-built book: 10 names, spread, sleeves in band."""
    return [
        _pos("A", 0.12, "Technology", "core"),
        _pos("B", 0.11, "Healthcare", "core"),
        _pos("C", 0.11, "Financial Services", "ballast"),
        _pos("D", 0.10, "Consumer Defensive", "core"),
        _pos("E", 0.10, "Industrials", "tactical"),
        _pos("F", 0.10, "Utilities", "ballast"),
        _pos("G", 0.10, "Communication Services", "core"),
        _pos("H", 0.10, "Energy", "tactical"),
        _pos("I", 0.10, "Consumer Cyclical", "core"),
        _pos("J", 0.06, "Basic Materials", "speculative"),
    ]


def test_balanced_book_scores_well_and_has_no_high_priority_actions():
    rep = ph.health_report(_balanced(), portfolio_beta=0.95)
    assert rep["score"] >= 85 and rep["grade"] == "A"
    assert not [r for r in rep["recommendations"] if r["priority"] == "high"]


def test_single_name_concentration_is_flagged_with_numbers():
    positions = [_pos("MSFT", 0.40), _pos("B", 0.20, "Healthcare"),
                 _pos("C", 0.20, "Energy"), _pos("D", 0.20, "Utilities")]
    rep = ph.health_report(positions, portfolio_beta=1.0)
    trim = next(r for r in rep["recommendations"] if r["action"] == "trim")
    assert trim["target"] == "MSFT" and trim["priority"] == "high"
    assert trim["from"] == 0.40 and trim["to"] == ph.MAX_SINGLE_NAME
    assert rep["dimensions"]["concentration"]["score"] < 100


def test_sector_concentration_and_missing_defensives():
    positions = [_pos(t, 0.25, "Technology") for t in "ABCD"]
    rep = ph.health_report(positions, portfolio_beta=1.2)
    actions = {r["action"] for r in rep["recommendations"]}
    assert "reduce_sector" in actions and "add_defensive" in actions
    dfs = next(r for r in rep["recommendations"] if r["action"] == "add_defensive")
    # All three defensive sectors are absent, so all three are named.
    assert set(dfs["target"]) == set(ph.DEFENSIVE_SECTORS)
    assert rep["dimensions"]["sector_balance"]["defensive_weight"] == 0.0


def test_speculative_sleeve_overweight_is_high_priority():
    positions = [_pos("A", 0.40, "Technology", "speculative"),
                 _pos("B", 0.30, "Healthcare", "speculative"),
                 _pos("C", 0.30, "Energy", "core")]
    rep = ph.health_report(positions, portfolio_beta=1.0)
    spec = next(r for r in rep["recommendations"]
                if r["action"] == "reduce_sleeve" and r["target"] == "speculative")
    assert spec["priority"] == "high"
    assert spec["from"] == 0.70 and spec["to"] == ph.SLEEVE_TARGETS["speculative"][1]


def test_beta_above_ceiling_recommends_reducing_it():
    rep = ph.health_report(_balanced(), portfolio_beta=1.60)
    beta_rec = next(r for r in rep["recommendations"] if r["action"] == "reduce_beta")
    assert beta_rec["from"] == 1.60 and beta_rec["to"] == ph.BETA_TARGET[1]
    assert rep["dimensions"]["risk_posture"]["score"] < 100
    # Inside the band -> full marks.
    ok = ph.health_report(_balanced(), portfolio_beta=0.90)
    assert ok["dimensions"]["risk_posture"]["score"] == 100.0


def test_correlated_cluster_is_hidden_concentration():
    """Five names in five different sectors that all trade together are one
    bet wearing several tickers — sector limits cannot see it."""
    positions = [_pos("A", 0.20, "Technology"), _pos("B", 0.20, "Industrials"),
                 _pos("C", 0.20, "Energy"), _pos("D", 0.20, "Utilities"),
                 _pos("E", 0.20, "Healthcare")]
    corr = {("A", "B"): 0.9, ("A", "C"): 0.85, ("A", "D"): 0.8}
    rep = ph.health_report(positions, portfolio_beta=1.0, corr=corr)
    cl = next(r for r in rep["recommendations"] if r["action"] == "break_cluster")
    assert set(cl["target"]) == {"A", "B", "C", "D"}
    assert cl["from"] == 0.80 and cl["priority"] == "high"


def test_weak_but_large_holding_is_surfaced_for_review():
    positions = [_pos("BAD", 0.30, "Energy", fund_score=25),
                 _pos("OK", 0.35, "Healthcare", fund_score=85),
                 _pos("FINE", 0.35, "Utilities", fund_score=80)]
    rep = ph.health_report(positions, portfolio_beta=1.0)
    rev = next(r for r in rep["recommendations"] if r["action"] == "review_holding")
    assert rev["target"] == "BAD" and rev["priority"] == "high"
    assert "BAD" in rep["dimensions"]["quality"]["weak_holdings"]


def test_missing_inputs_drop_out_rather_than_scoring_zero():
    """No beta, no correlations, no fundamentals -> those dimensions are absent
    from the composite, not counted as failures."""
    positions = [{"ticker": "A", "weight": 0.5, "sector": "Technology"},
                 {"ticker": "B", "weight": 0.5, "sector": "Healthcare"}]
    rep = ph.health_report(positions)
    assert rep["dimensions"]["risk_posture"]["score"] is None
    assert "correlation" not in rep["dimensions"]
    assert "quality" not in rep["dimensions"]
    assert rep["score"] is not None          # still scored on what IS known


def test_excess_return_is_reported_against_the_benchmark():
    rep = ph.health_report(_balanced(), equity_metrics={"twr_pct": 8.0,
                                                        "sharpe_ann": 1.2,
                                                        "max_drawdown_pct": -5.0,
                                                        "n_snapshots": 40},
                           portfolio_beta=1.0, benchmark_return_pct=5.0)
    assert rep["performance"]["excess_pct"] == 3.0     # alpha, not raw return


def test_empty_book():
    rep = ph.health_report([])
    assert rep["score"] is None and rep["recommendations"] == []
