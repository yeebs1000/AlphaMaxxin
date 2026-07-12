"""Risk, signals, performance, sizing — hand-computed values on synthetic
inputs."""
import numpy as np
import pytest

from app.skills import risk, signals, performance, portfolio_construction, fx

HOLDINGS = [
    {"ticker": "AAA", "company": "Alpha", "quantity": 10, "cost_price": 50.0, "currency": "USD"},
    {"ticker": "BBB", "company": "Beta", "quantity": 20, "cost_price": 20.0, "currency": "USD"},
    {"ticker": "CCC", "company": "Gamma", "quantity": 100, "cost_price": 5.0, "currency": "SGD"},
]


# ---------------------------------------------------------------------------
# risk
# ---------------------------------------------------------------------------
def test_hhi_and_weights():
    values = {"AAA": 500.0, "BBB": 300.0, "CCC": 200.0}
    report = risk.compute_risk(HOLDINGS, values)
    assert report["portfolio_value_usd"] == 1000.0
    assert report["weights"]["AAA"] == pytest.approx(0.5)
    # HHI = 0.5² + 0.3² + 0.2² = 0.38
    assert report["hhi"] == pytest.approx(0.38)
    assert report["top_position"] == {"ticker": "AAA", "weight": pytest.approx(0.5)}
    assert any("AAA" in f for f in report["flags"])  # >20% single name


def test_currency_exposure_flag():
    values = {"AAA": 100.0, "BBB": 100.0, "CCC": 800.0}
    report = risk.compute_risk(HOLDINGS, values)
    assert report["currency_exposure"]["SGD"] == pytest.approx(0.8)
    assert any("SGD" in f for f in report["flags"])


def test_beta_one_when_portfolio_is_benchmark():
    rng = np.random.default_rng(7)
    rets = rng.normal(0, 0.01, 252).tolist()
    values = {"AAA": 1000.0}
    holdings = [HOLDINGS[0]]
    report = risk.compute_risk(holdings, values, returns={"AAA": rets},
                               benchmark_returns=rets)
    assert report["portfolio_beta"] == pytest.approx(1.0, abs=1e-9)
    assert report["var_95_1d_pct"] < 0  # 5th percentile of centered returns
    assert report["cvar_95_1d_pct"] <= report["var_95_1d_pct"]
    assert report["max_drawdown_pct"] < 0


def test_high_correlation_pairs():
    rng = np.random.default_rng(3)
    base = rng.normal(0, 0.01, 100)
    a = base.tolist()
    b = (base + rng.normal(0, 0.001, 100)).tolist()   # ~identical → corr>0.8
    c = rng.normal(0, 0.01, 100).tolist()             # independent
    values = {"AAA": 300.0, "BBB": 300.0, "CCC": 400.0}
    report = risk.compute_risk(HOLDINGS, values,
                               returns={"AAA": a, "BBB": b, "CCC": c})
    pairs = {(p["a"], p["b"]) for p in report["high_correlation_pairs"]}
    assert ("AAA", "BBB") in pairs or ("BBB", "AAA") in pairs
    assert all("CCC" not in p for p in pairs)


def test_stress_scenarios_beta_and_fx_legs():
    rng = np.random.default_rng(7)
    rets = rng.normal(0, 0.01, 252).tolist()
    # Beta = 1 (portfolio is the benchmark); 20% of book in SGD.
    values = {"AAA": 500.0, "BBB": 300.0, "CCC": 200.0}
    report = risk.compute_risk(HOLDINGS, values,
                               returns={"AAA": rets, "BBB": rets, "CCC": rets},
                               benchmark_returns=rets)
    by_name = {s["scenario"]: s for s in report["stress_scenarios"]}
    crash = by_name["index -20% (crash)"]
    assert crash["est_pnl_pct"] == pytest.approx(-20.0, abs=0.1)
    assert crash["est_pnl_usd"] == pytest.approx(-200.0, abs=2)
    assert crash["beta_assumed"] is False
    fx_only = by_name["USD +5% (FX shock only)"]
    assert fx_only["est_pnl_pct"] == pytest.approx(-0.2 * 5.0, abs=0.01)  # 20% SGD
    risk_off = by_name["risk-off (index -10%, USD +3%)"]
    assert risk_off["est_pnl_pct"] == pytest.approx(-10.0 - 0.2 * 3.0, abs=0.1)


def test_stress_scenarios_without_returns_flags_assumed_beta():
    report = risk.compute_risk(HOLDINGS, {"AAA": 1000.0})
    assert all(s["beta_assumed"] for s in report["stress_scenarios"])


def test_liquidity_days_to_exit():
    values = {"AAA": 1000.0, "BBB": 100.0}
    adv = {"AAA": 100.0, "BBB": 10000.0}   # AAA: 1000/(100*0.1) = 100 days
    report = risk.compute_risk(HOLDINGS[:2], values, adv_usd=adv)
    liq = report["liquidity"]
    assert liq["days_to_liquidate_10pct"]["AAA"] == pytest.approx(100.0)
    assert liq["days_to_liquidate_10pct"]["BBB"] == pytest.approx(0.1)
    assert liq["slow_to_exit"] == ["AAA"]
    # No ADV supplied → no liquidity block at all.
    assert "liquidity" not in risk.compute_risk(HOLDINGS, values)


def test_diversification_ratio_one_bet_vs_spread():
    rng = np.random.default_rng(3)
    base = rng.normal(0, 0.01, 100)
    same = {"AAA": base.tolist(), "BBB": base.tolist(), "CCC": base.tolist()}
    values = {"AAA": 300.0, "BBB": 300.0, "CCC": 400.0}
    clones = risk.compute_risk(HOLDINGS, values, returns=same)
    assert clones["diversification_ratio"] == pytest.approx(1.0, abs=0.01)
    assert clones["avg_pairwise_correlation"] == pytest.approx(1.0, abs=0.01)
    indep = {"AAA": rng.normal(0, 0.01, 100).tolist(),
             "BBB": rng.normal(0, 0.01, 100).tolist(),
             "CCC": rng.normal(0, 0.01, 100).tolist()}
    spread = risk.compute_risk(HOLDINGS, values, returns=indep)
    assert spread["diversification_ratio"] > 1.3   # real diversification


# ---------------------------------------------------------------------------
# fx / performance
# ---------------------------------------------------------------------------
def test_fx_live_and_fallback():
    assert fx.usd_rate("USD") == 1.0
    assert fx.usd_rate("SGD", {"SGD": 0.75}) == 0.75
    assert fx.usd_rate("SGD", {}) == fx.FALLBACK_USD_PER["SGD"]
    assert fx.to_usd(100, "SGD", {"SGD": 0.8}) == pytest.approx(80.0)


def test_portfolio_summary_totals():
    quotes = {
        "AAA": {"price": 60.0, "currency": "USD", "change_pct": 1.0},
        "BBB": {"price": 25.0, "currency": "USD", "change_pct": -2.0},
        "CCC": {"price": 4.0, "currency": "SGD", "change_pct": None},
    }
    s = performance.portfolio_summary(HOLDINGS, quotes, fx_rates={"SGD": 0.75})
    # AAA 10*60=600, BBB 20*25=500, CCC 100*4*0.75=300
    assert s["total_value_usd"] == pytest.approx(1400.0)
    # cost: 500 + 400 + 100*5*0.75=375 → 1275
    assert s["total_cost_usd"] == pytest.approx(1275.0)
    assert s["total_pl_usd"] == pytest.approx(125.0)
    # day change: 600*1% - 500*2% = -4
    assert s["day_change_usd"] == pytest.approx(-4.0)
    assert s["by_currency"]["SGD"] == pytest.approx(300.0)
    weights = {r["ticker"]: r["weight"] for r in s["holdings"]}
    assert sum(weights.values()) == pytest.approx(1.0)


def test_portfolio_summary_missing_quote_reported():
    s = performance.portfolio_summary(HOLDINGS, {"AAA": {"price": 60.0, "currency": "USD"}})
    assert s["holdings_count"] == 1
    assert len(s["errors"]) == 2


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------
def test_aggregate_technical_only():
    tech = {"signal": {"score": 60}}
    out = signals.aggregate("AAA", tech)
    assert out["composite_score"] == pytest.approx(60.0)  # single component
    assert out["components"]["fundamental"] is None
    assert out["conviction"] == "low"  # low coverage caps conviction


def test_aggregate_blends_components():
    tech = {"signal": {"score": 80}}
    fund = {"price": 100, "growth": {"rev_yoy": 0.2}, "margins": {"net": 0.2},
            "analyst": {"target_mean": 130}, "quality_flags": []}
    sentiment = {"AAA": {"count": 5, "avg_score": 0.4, "bullish": 4, "bearish": 0}}
    risk_report = {"weights": {"AAA": 0.05}, "high_correlation_pairs": []}
    out = signals.aggregate("AAA", tech, fund, sentiment, risk_report)
    assert out["coverage"] == 1.0
    # fundamental: 25+20+25 = 70; news: 0.4*200=80; risk: 0
    expected = (0.45 * 80 + 0.25 * 70 + 0.15 * 80 + 0.15 * 0)
    assert out["composite_score"] == pytest.approx(expected, abs=0.1)
    assert out["conviction"] == "high"


def test_aggregate_no_data():
    out = signals.aggregate("ZZZ", None)
    assert out["composite_score"] is None
    assert out["conviction"] == "none"


def test_position_guidance_pl():
    snaps = {"AAA": {"last_close": 60.0, "rsi14": 55.0,
                     "signal": {"score": 30, "label": "buy", "reasons": ["r"]}}}
    rows = signals.position_guidance([HOLDINGS[0]], snaps)
    assert rows[0]["pl_pct"] == pytest.approx(20.0)  # 50 → 60
    assert rows[0]["label"] == "buy"


# ---------------------------------------------------------------------------
# recommendation_block
# ---------------------------------------------------------------------------
def test_recommendation_block_uses_analyst_target():
    tech = {"last_close": 100.0, "atr14": 5.0}
    fund = {"analyst": {"target_mean": 130.0}}
    block = signals.recommendation_block("AAA", tech, fund, atr_stop=88.0,
                                         composite={"conviction": "high", "composite_score": 60})
    assert block["current_price"] == 100.0
    assert block["entry_range"] == [97.5, 102.5]
    assert block["bull_target"] == 130.0
    assert block["base_target"] == pytest.approx(115.0)   # midpoint(100, 130)
    assert block["bear_stop"] == 88.0                     # from sizing, not recomputed
    assert block["risk_reward_base"] == pytest.approx((115 - 100) / (100 - 88))
    assert block["target_source"] == "analyst consensus"
    assert block["conviction"] == "high"


def test_recommendation_block_falls_back_to_atr_projection():
    tech = {"last_close": 50.0, "atr14": 2.0}
    block = signals.recommendation_block("BBB", tech, fundamentals_snap=None, atr_stop=None)
    assert block["bull_target"] == pytest.approx(56.0)   # price + 3*ATR
    assert block["bear_stop"] == pytest.approx(46.0)     # price - 2*ATR, since no sizing given
    assert "no analyst target" in block["target_source"]


def test_recommendation_block_none_without_technicals():
    assert signals.recommendation_block("CCC", None) is None
    assert signals.recommendation_block("CCC", {"last_close": 100.0}) is None  # no ATR


# ---------------------------------------------------------------------------
# portfolio_construction
# ---------------------------------------------------------------------------
def _summary(weights: dict) -> dict:
    total = 1000.0
    return {"holdings": [{"ticker": t, "weight": w, "value_usd": w * total}
                         for t, w in weights.items()]}


def test_single_name_cap_triggers_trim():
    s = _summary({"AAA": 0.5, "BBB": 0.3, "CCC": 0.2})
    out = portfolio_construction.suggest_sizing(s, composites={})
    by_ticker = {r["ticker"]: r for r in out}
    assert by_ticker["AAA"]["action"] == "trim"
    assert "cap" in by_ticker["AAA"]["rationale"]


def test_positive_signal_accumulates():
    s = _summary({"AAA": 0.05, "BBB": 0.05, "CCC": 0.9})
    comps = {"AAA": {"composite_score": 100}}
    out = portfolio_construction.suggest_sizing(s, comps)
    by_ticker = {r["ticker"]: r for r in out}
    # CCC over cap dominates the renormalization; AAA tilted up
    assert by_ticker["AAA"]["suggested_wt"] > by_ticker["AAA"]["current_wt"]
    assert by_ticker["CCC"]["action"] == "trim"


def test_atr_stop_uses_2x_atr():
    s = _summary({"AAA": 0.5, "BBB": 0.5})
    snaps = {"AAA": {"atr14": 2.0, "last_close": 100.0}}
    out = portfolio_construction.suggest_sizing(s, {}, technical_snaps=snaps)
    by_ticker = {r["ticker"]: r for r in out}
    assert by_ticker["AAA"]["atr_stop"] == pytest.approx(96.0)
    assert by_ticker["BBB"]["atr_stop"] is None
