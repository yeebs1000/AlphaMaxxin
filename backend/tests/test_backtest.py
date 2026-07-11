"""Backtest engine: no lookahead, sane aggregation, synthetic-trend sanity."""
import numpy as np

from app.skills import backtest


def _bars(n=400, drift=0.0, seed=0):
    rng = np.random.default_rng(seed)
    closes = list(np.cumsum(rng.normal(drift, 1.0, n)) + 200)
    return {"closes": closes, "highs": [c * 1.01 for c in closes],
            "lows": [c * 0.99 for c in closes],
            "volumes": list(rng.integers(1000, 5000, n).astype(float))}


def test_events_have_no_lookahead():
    b = _bars()
    events = backtest.collect_events("X", b, step=25)
    assert events, "should produce events"
    # Mutating bars AFTER an event's outcome window must not change the event.
    e = events[0]
    cutoff = e["bar"] + backtest.RESOLUTION_WINDOW + 1
    tampered = {k: list(v) for k, v in b.items()}
    tampered["closes"][cutoff + 5] += 500
    tampered["highs"][cutoff + 5] += 500
    e2 = backtest.collect_events("X", tampered, step=25)[0]
    assert e == e2


def test_aggregate_shapes_and_baseline():
    events = backtest.collect_events("X", _bars(n=500), step=10)
    results = backtest.aggregate(events)
    assert results["n_events"] == len(events)
    assert set(results["baseline_fwd"]) == {20, 60}
    assert results["stop_target"]["n"] == len(events)
    assert (results["stop_target"]["stop_first"]
            + results["stop_target"]["target_first"]
            + results["stop_target"]["unresolved_60d"]) == len(events)
    assert 1 <= len(results["score_quintiles"]) <= 5
    report = backtest.format_report(results)
    assert "mechanical-score quintiles" in report


def test_uptrend_events_skew_positive():
    # Strong drift → forward returns positive; targets hit far more than stops.
    results = backtest.run({"UP": _bars(n=600, drift=0.6, seed=1)}, step=10)
    assert results["baseline_fwd"][60] > 0
    st = results["stop_target"]
    assert st["target_rate"] is None or st["target_rate"] > 0.5


def test_run_skips_short_histories():
    assert backtest.run({"TINY": _bars(n=100)}) == {"n_events": 0}
