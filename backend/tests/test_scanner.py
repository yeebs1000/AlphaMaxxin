"""Scanner: conviction gate, one-shot dedup with re-arm, cloud budget."""
import datetime

from app import scanner

D = datetime.date


def _snap(score=40, rsi=50):
    return {"signal": {"score": score, "reasons": ["r1", "r2", "r3", "r4"]},
            "rsi14": rsi}


def test_gate_band_rsi_and_regime():
    snaps = {"BAND": _snap(score=40, rsi=50),      # productive band
             "OVERSOLD": _snap(score=10, rsi=25),  # rsi edge, weak score
             "EXTENDED": _snap(score=75, rsi=65),  # extreme score → excluded
             "NEITHER": _snap(score=10, rsi=50)}
    out = scanner.gate_candidates(snaps, index_ok=True)
    got = {s["ticker"]: s["setup"] for s in out}
    assert got == {"BAND": "productive_trend", "OVERSOLD": "rsi_reversion"}
    assert all(len(s["reasons"]) <= 3 for s in out)
    # Regime gate kills everything.
    assert scanner.gate_candidates(snaps, index_ok=False) == []


def test_gate_prioritizes_chokepoints():
    snaps = {"MSFT": _snap(score=50), "AXTI": _snap(score=30)}
    out = scanner.gate_candidates(snaps, index_ok=True)
    assert out[0]["ticker"] == "AXTI" and out[0]["chokepoint"] is True


def test_dedupe_one_shot_and_rearm():
    s = [{"ticker": "A", "setup": "rsi_reversion", "direction": "long",
          "score": 30, "chokepoint": False, "reasons": []}]
    fresh, state = scanner.dedupe(s, {}, D(2026, 7, 20))
    assert len(fresh) == 1                              # first fire
    fresh2, state = scanner.dedupe(s, state, D(2026, 7, 20))
    assert fresh2 == []                                 # persists → disarmed
    fresh3, state = scanner.dedupe(s, state, D(2026, 7, 21))
    assert fresh3 == []                                 # still persisting
    # Setup disappears for a day → fingerprint re-arms…
    _, state = scanner.dedupe([], state, D(2026, 7, 22))
    fresh4, state = scanner.dedupe(s, state, D(2026, 7, 23))
    assert len(fresh4) == 1                             # …and fires again


def test_cloud_budget(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    cfg = {"max_cloud_runs_per_day": 2}
    state = {}
    today = D(2026, 7, 20)
    assert scanner._cloud_budget_ok(state, today, cfg)
    scanner._mark_cloud_run(state, today)
    scanner._mark_cloud_run(state, today)
    assert not scanner._cloud_budget_ok(state, today, cfg)   # cap reached
    assert scanner._cloud_budget_ok(state, D(2026, 7, 21), cfg)  # resets daily
    # Local endpoint → always free.
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    assert scanner._cloud_budget_ok(state, today, cfg)
