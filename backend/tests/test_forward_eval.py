"""Forward evaluation: the pre-registration lock and the metrics.

The most important test in this file is the first one. Everything else checks
arithmetic; that one checks honesty.
"""
import inspect
import io
import json
import math
import tokenize

import pytest

from app.skills import forward_eval as fe


# ---------------------------------------------------------------------------
# pre-registration
# ---------------------------------------------------------------------------
def test_the_protocol_is_locked():
    """Pre-registration only means something if changing it is visible.

    The hash is pinned in the module. Edit a horizon, a bucket count, a cost
    assumption or the primary metric and this fails until the pin is updated in
    the same commit — which is exactly the review moment that separates "we
    pre-registered" from "we tuned it after seeing the result".
    """
    assert fe.protocol_hash() == fe.PROTOCOL_HASH, (
        "PROTOCOL changed without updating PROTOCOL_HASH — if the change was "
        "deliberate, update the pin in this commit and say why")


def test_the_protocol_names_one_primary_metric():
    """With 3 regions x 4 families x 2 horizons there are dozens of ways to
    find a result that is not there. Exactly one is primary."""
    assert isinstance(fe.PROTOCOL["primary_metric"], str)
    assert fe.PROTOCOL["primary_metric"] not in fe.PROTOCOL["secondary_metrics"]


def test_the_protocol_states_a_failure_criterion_in_advance():
    """A hypothesis that cannot fail is not a hypothesis."""
    assert "not predictive" in fe.PROTOCOL["failure_criteria"]
    assert fe.PROTOCOL["min_snapshots_before_reporting"] >= 12


def test_the_protocol_disclaims_a_historical_backtest():
    joined = " ".join(fe.PROTOCOL["not_claimed"]).lower()
    assert "no historical backtest" in joined
    assert "not point-in-time" in joined


# ---------------------------------------------------------------------------
# spearman
# ---------------------------------------------------------------------------
def test_spearman_perfect_and_inverse():
    assert fe.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert fe.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_is_rank_based_not_value_based():
    """A single outlier must not dominate — the reason for rank correlation."""
    assert fe.spearman([1, 2, 3, 4], [10, 20, 30, 10_000]) == pytest.approx(1.0)


def test_spearman_is_undefined_not_zero_when_one_side_is_constant():
    """An entirely tied side has no rank variation. Reporting 0.0 would read as
    'no relationship measured' when the truth is 'no measurement possible'."""
    assert fe.spearman([1, 1, 1, 1], [1, 2, 3, 4]) is None


def test_spearman_needs_three_points():
    assert fe.spearman([1, 2], [1, 2]) is None
    assert fe.spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# forward return
# ---------------------------------------------------------------------------
def bars(prices, start_day=1):
    return {f"2026-01-{start_day + i:02d}": p for i, p in enumerate(prices)}


def test_forward_return_counts_trading_bars_not_calendar_days():
    """20 trading days is the horizon. Counting calendar days would silently
    vary the window with holidays and make snapshots incomparable."""
    series = {"2026-01-01": 100.0, "2026-01-05": 110.0, "2026-01-09": 121.0}
    assert fe.forward_return(series, "2026-01-01", 1) == pytest.approx(0.10)
    assert fe.forward_return(series, "2026-01-01", 2) == pytest.approx(0.21)


def test_forward_return_uses_the_last_bar_on_or_before_as_of():
    series = bars([100.0, 105.0, 110.0])
    # as_of falls between bars: the snapshot saw 2026-01-02's close.
    assert fe.forward_return(series, "2026-01-02", 1) == pytest.approx(110.0 / 105 - 1)


def test_forward_return_is_none_when_the_window_does_not_close():
    """A delisted or halted name has no forward return. Imputing zero would
    flatter whichever bucket happened to hold it."""
    assert fe.forward_return(bars([100.0, 101.0]), "2026-01-01", 20) is None
    assert fe.forward_return({}, "2026-01-01", 1) is None
    assert fe.forward_return(None, "2026-01-01", 1) is None


def test_forward_return_ignores_non_positive_and_null_prices():
    series = {"2026-01-01": 100.0, "2026-01-02": None, "2026-01-03": 0.0,
              "2026-01-04": 120.0}
    assert fe.forward_return(series, "2026-01-01", 1) == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# buckets, turnover, sample size
# ---------------------------------------------------------------------------
def test_bucket_spread_is_top_minus_bottom():
    scored = [(float(i), float(i) / 100) for i in range(1, 11)]
    result = fe.bucket_spread(scored, buckets=5)
    assert result["bucket_size"] == 2
    assert result["top_mean"] == pytest.approx(0.095)     # (0.09 + 0.10) / 2
    assert result["bottom_mean"] == pytest.approx(0.015)  # (0.01 + 0.02) / 2
    assert result["spread"] == pytest.approx(0.08)


def test_bucket_spread_refuses_a_pool_too_small_to_bucket():
    assert fe.bucket_spread([(1.0, 0.1)] * 5, buckets=5)["spread"] is None


def test_turnover_is_the_fraction_of_the_top_bucket_replaced():
    assert fe.turnover(["A", "B", "C", "D"], ["A", "B", "C", "D"]) == 0.0
    assert fe.turnover(["A", "B", "C", "D"], ["A", "B", "X", "Y"]) == pytest.approx(0.5)
    assert fe.turnover([], ["A"]) == 1.0
    assert fe.turnover(["A"], []) is None


def test_effective_sample_size_discounts_overlapping_windows():
    """12 weekly snapshots at a 20-day horizon are not 12 independent
    observations — they are about 3. This is the number that stops a headline
    being computed on n=12."""
    assert fe.effective_sample_size(12, 20, 5) == pytest.approx(3.0)
    assert fe.effective_sample_size(12, 5, 5) == pytest.approx(12.0)
    assert fe.effective_sample_size(0, 20, 5) is None


# ---------------------------------------------------------------------------
# end-to-end on synthetic data with a known answer
# ---------------------------------------------------------------------------
def snapshot_with(signal: str, n: int = 20) -> tuple:
    """A snapshot plus prices engineered so the true IC is known.

    signal="perfect": forward return rises with score  -> IC = +1
    signal="inverse": forward return falls with score  -> IC = -1
    signal="none":    forward return is flat in rank   -> IC undefined/0
    """
    entries, prices = [], {}
    for i in range(n):
        ticker = f"T{i:02d}"
        score = float(i)
        if signal == "perfect":
            ret = 0.01 * i
        elif signal == "inverse":
            ret = -0.01 * i
        else:
            ret = 0.05
        entries.append({"ticker": ticker, "experimental_score": score,
                        "peer_pool": "US|industry|Semis"})
        prices[ticker] = {"2026-01-01": 100.0,
                          "2026-01-02": 100.0 * (1 + ret)}
    return {"as_of": "2026-01-01", "entries": entries}, prices


def test_evaluate_recovers_a_perfect_signal():
    snapshot, prices = snapshot_with("perfect")
    result = fe.evaluate_snapshot(snapshot, prices, horizon=1)
    assert result["pooled_ic"] == pytest.approx(1.0)
    assert result["names_evaluated"] == 20


def test_evaluate_recovers_an_inverse_signal():
    snapshot, prices = snapshot_with("inverse")
    assert fe.evaluate_snapshot(snapshot, prices, horizon=1)["pooled_ic"] \
        == pytest.approx(-1.0)


def test_evaluate_reports_no_ic_when_returns_are_flat():
    snapshot, prices = snapshot_with("none")
    assert fe.evaluate_snapshot(snapshot, prices, horizon=1)["pooled_ic"] is None


def test_evaluate_pools_separately_and_weights_by_size():
    """An IC across every name would mostly measure sector drift rather than
    the peer-relative judgement the score actually makes."""
    good, prices = snapshot_with("perfect", n=20)
    bad, bad_prices = snapshot_with("inverse", n=12)
    for entry in bad["entries"]:
        entry["ticker"] += "B"
        entry["peer_pool"] = "US|industry|Software"
    prices.update({k + "B": v for k, v in bad_prices.items()})
    merged = {"as_of": "2026-01-01", "entries": good["entries"] + bad["entries"]}
    result = fe.evaluate_snapshot(merged, prices, horizon=1)
    assert len(result["pools"]) == 2
    # (1.0 * 20 + -1.0 * 12) / 32
    assert result["pooled_ic"] == pytest.approx((20 - 12) / 32)


def test_evaluate_skips_pools_below_the_minimum():
    snapshot, prices = snapshot_with("perfect", n=5)
    result = fe.evaluate_snapshot(snapshot, prices, horizon=1)
    assert result["pooled_ic"] is None
    assert result["pools"][0]["reason"] == "below min_names_per_pool"


def test_evaluate_counts_what_it_dropped():
    snapshot, prices = snapshot_with("perfect")
    snapshot["entries"].append({"ticker": "NOSCORE",
                                "experimental_score": None,
                                "peer_pool": "US|industry|Semis"})
    snapshot["entries"].append({"ticker": "DELISTED",
                                "experimental_score": 5.0,
                                "peer_pool": "US|industry|Semis"})
    result = fe.evaluate_snapshot(snapshot, prices, horizon=1)
    assert result["dropped"] == {"no_score": 1, "no_forward_price": 1}


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------
def test_summarize_refuses_a_verdict_before_the_registered_minimum():
    evaluations = [{"pooled_ic": 0.9, "horizon_trading_days": 20}] * 3
    summary = fe.summarize(evaluations)
    assert summary["ready_to_report"] is False
    assert summary["verdict"] is None, "a verdict on 3 snapshots is not a verdict"
    assert summary["mean_ic"] == pytest.approx(0.9)


def test_summarize_calls_a_null_result_a_null_result():
    evaluations = [{"pooled_ic": 0.001, "horizon_trading_days": 20}] * 12
    summary = fe.summarize(evaluations)
    assert summary["ready_to_report"] is True
    assert "not predictive" in summary["verdict"]


def test_summarize_always_reports_effective_sample_size_and_the_caveat():
    summary = fe.summarize(
        [{"pooled_ic": 0.3, "horizon_trading_days": 20}] * 12)
    assert summary["effective_sample_size"] == pytest.approx(3.0)
    assert "overlapping windows" in summary["caveat"]
    assert summary["protocol_hash"] == fe.PROTOCOL_HASH


def test_summarize_handles_no_evaluations():
    summary = fe.summarize([])
    assert summary["snapshots_evaluated"] == 0 and summary["mean_ic"] is None
    json.dumps(summary, allow_nan=False)


# ---------------------------------------------------------------------------
# purity
# ---------------------------------------------------------------------------
def test_module_is_inert():
    source = inspect.getsource(fe)
    lines = source.splitlines(keepends=True)
    spans = [(t.start, t.end) for t in
             tokenize.generate_tokens(io.StringIO(source).readline)
             if t.type in (tokenize.COMMENT, tokenize.STRING)]
    for (srow, scol), (erow, ecol) in reversed(spans):
        if srow == erow:
            line = lines[srow - 1]
            lines[srow - 1] = line[:scol] + " " * (ecol - scol) + line[ecol:]
        else:
            lines[srow - 1] = lines[srow - 1][:scol] + "\n"
            for row in range(srow, erow - 1):
                lines[row] = "\n"
            lines[erow - 1] = lines[erow - 1][ecol:]
    code = "".join(lines)
    for banned in ("import os", "import time", "import datetime", "open(",
                   "requests", "urllib", "from ..llm", "from ..brokers",
                   "openai", "anthropic", "time.time"):
        assert banned not in code, f"forward_eval reaches {banned}"
