"""Allocation and return-calendar regressions; fixture data only."""
import datetime

import numpy as np
import pytest

from app.skills import portfolio_construction as pc, risk


def test_signal_sizing_keeps_final_feasible_weights_under_cap():
    weights = {"A": 0.4, **{t: 0.1 for t in "BCDEFG"}}
    out = pc.suggest_sizing({"holdings": [
        {"ticker": t, "weight": w} for t, w in weights.items()]}, {})
    assert max(r["suggested_wt"] for r in out) <= 0.15
    assert sum(r["suggested_wt"] for r in out) == pytest.approx(1, abs=0.0005)


def test_signal_sizing_reports_cash_when_cap_makes_full_investment_impossible():
    out = pc.suggest_sizing({"holdings": [
        {"ticker": t, "weight": w} for t, w in {"A": 0.5, "B": 0.3, "C": 0.2}.items()]}, {})
    assert [r["suggested_wt"] for r in out] == [0.15] * 3
    assert out[0]["cash_remainder_wt"] == pytest.approx(0.55)


def test_covariance_redistribution_keeps_already_capped_names_pinned():
    rng = np.random.default_rng(7)
    raw = [0.75, 0.15, 0.07, 0.02, 0.01]
    returns = {f"T{i}": rng.normal(0, 0.002 / np.sqrt(w), 6000).tolist()
               for i, w in enumerate(raw)}
    out = pc.min_variance_tilt({t: 0.2 for t in returns}, returns, cap=0.30)
    assert max(out["suggested_weights"].values()) <= 0.30
    assert sum(out["suggested_weights"].values()) == pytest.approx(1, abs=0.0005)


def test_fractional_covariance_cap_is_not_breached_by_output_rounding():
    rng = np.random.default_rng(5)
    returns = {t: rng.normal(0, sd, 200).tolist()
               for t, sd in {"A": 0.001, "B": 0.03, "C": 0.012, "D": 0.015}.items()}
    out = pc.min_variance_tilt({t: 0.25 for t in returns}, returns, cap=0.30006)
    assert max(out["suggested_weights"].values()) <= 0.30006


def test_zero_value_book_does_not_get_invented_allocations():
    out = pc.suggest_sizing({"holdings": [{"ticker": "A", "weight": 0.0}]}, {})
    assert out[0]["suggested_wt"] == 0


def test_first_period_loss_counts_toward_drawdown():
    out = risk.compute_risk([{"ticker": "A"}], {"A": 1000},
                            {"A": [-0.5] + [0.0] * 20})
    assert out["max_drawdown_pct"] == -50


def test_mismatched_naked_return_arrays_are_unavailable_not_tail_aligned():
    returns = {"A": [0.01, -0.01] * 20, "B": [0.01, -0.01] * 19}
    out = risk.compute_risk([{"ticker": "A"}, {"ticker": "B"}],
                            {"A": 500, "B": 500}, returns)
    assert "ann_volatility_pct" not in out
    assert out.get("alignment_note")
    assert pc.min_variance_tilt({"A": 0.34, "B": 0.33, "C": 0.33},
                               {**returns, "C": [0.01] * 60}, min_bars=20,
                               cap=0.40) is None


def test_benchmark_length_mismatch_withholds_beta():
    out = risk.compute_risk([{"ticker": "A"}], {"A": 1000},
                            {"A": [0.01, -0.01] * 20},
                            benchmark_returns=[0.01, -0.01] * 19)
    assert "portfolio_beta" not in out
    assert out.get("benchmark_alignment_note")


@pytest.mark.parametrize("missing_value", [None, float("nan"), float("inf")])
def test_incomplete_valuation_withholds_whole_book_risk(missing_value):
    holdings = [{"ticker": "A", "quantity": 10}, {"ticker": "B", "quantity": 90}]
    values = {"A": 1000}
    if missing_value is not None:
        values["B"] = missing_value
    out = risk.compute_risk(holdings, values, {"A": [0.01, -0.01] * 20})
    assert out["portfolio_value_usd"] is None
    assert out["weights"] == {}
    assert out["valuation_errors"]
    assert "portfolio_beta" not in out
    assert "hhi" not in out


def test_incomplete_summary_cannot_produce_sizing_recommendations():
    out = pc.suggest_sizing({"holdings": [{"ticker": "A", "weight": 1.0}],
                             "errors": ["no quote for B"]}, {})
    assert out == []


def test_multiday_intervals_cannot_be_reported_as_one_day_or_annualized_daily_risk():
    rets = [0.04, -0.04] * 15
    out = risk.compute_risk([{"ticker": "A", "quantity": 10}], {"A": 1000},
                            {"A": rets}, benchmark_returns=rets,
                            return_interval_days=[5] * 30)
    assert "var_95_1d_pct" not in out
    assert "cvar_95_1d_pct" not in out
    assert "ann_volatility_pct" not in out
    assert out["portfolio_beta"] == pytest.approx(1)
    assert out["max_drawdown_pct"] < 0
    assert out["interval_note"]


def test_weekend_alignment_is_one_business_day_but_missing_weekdays_are_not():
    from app.skills.return_alignment import align_daily_returns
    out = align_daily_returns({"A": {
        "timestamps": ["2026-01-02", "2026-01-05", "2026-01-12"],
        "closes": [100, 110, 121]}})
    assert out["interval_business_days"] == [1, 5]


def test_holiday_alignment_uses_common_close_intervals_for_assets_and_benchmark():
    from app.skills.return_alignment import align_daily_returns
    out = align_daily_returns({
        "A": {"timestamps": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
              "closes": [100, 110, 120, 144]},
        "B": {"timestamps": ["2026-01-01", "2026-01-03", "2026-01-04"],
              "closes": [100, 120, 144]},
    }, {"timestamps": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        "closes": [200, 205, 220, 242]})
    assert out["dates"] == ["2026-01-03", "2026-01-04"]
    assert out["returns"]["A"] == pytest.approx([0.2, 0.2])
    assert out["returns"]["B"] == pytest.approx([0.2, 0.2])
    assert out["benchmark_returns"] == pytest.approx([0.1, 0.1])
    assert "historical_fx_not_included" in out["basis"]


def test_alignment_sorts_deduplicates_utc_dates_and_excludes_missing_dates():
    from app.skills.return_alignment import align_daily_returns
    stamp = datetime.datetime(2026, 1, 3, tzinfo=datetime.timezone.utc).timestamp()
    out = align_daily_returns({
        "A": {"timestamps": [stamp, "2026-01-01", "2026-01-02T23:00:00+00:00",
                              "2026-01-03"], "closes": [130, 100, 110, 132]},
        "NO_DATES": {"closes": [100, 110, 132]},
    })
    assert out["returns"]["A"] == pytest.approx([0.1, 0.2])
    assert "NO_DATES" in out["excluded"]
    assert out["benchmark_returns"] is None
