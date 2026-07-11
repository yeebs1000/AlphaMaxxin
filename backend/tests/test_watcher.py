"""Holdings watcher: triggers, market gating, dedup, escalation cap."""
from datetime import datetime, timezone

from app import watcher

# Wed 2026-07-08 18:00 UTC = 14:00 New York → US open, Asia closed.
US_OPEN = datetime(2026, 7, 8, 18, 0, tzinfo=timezone.utc)


def _holding(ticker):
    return {"ticker": ticker, "company": ticker, "quantity": 1.0,
            "cost_price": 1.0, "currency": "USD"}


def test_triggers_fire_and_closed_markets_skipped():
    holdings = [_holding("STP"), _holding("TGT"), _holding("MOV"),
                _holding("ERN"), _holding("9988.HK")]  # HK closed at 18:00 UTC
    levels = {"STP": {"bear_stop": 90.0, "base_target": 120.0},
              "TGT": {"bear_stop": 90.0, "base_target": 120.0},
              "9988.HK": {"bear_stop": 90.0, "base_target": 120.0}}
    quotes = {"STP": {"price": 89.0, "change_pct": -1.0},
              "TGT": {"price": 121.0, "change_pct": 1.0},
              "MOV": {"price": 50.0, "change_pct": -6.2},
              "ERN": {"price": 10.0, "change_pct": 0.1},
              "9988.HK": {"price": 80.0, "change_pct": -9.0}}
    alerts, state = watcher.check(holdings, levels, quotes,
                                  {"ERN": "2026-07-10"}, {}, US_OPEN)
    fired = {(a["ticker"], a["trigger"]) for a in alerts}
    assert fired == {("STP", "stop_breach"), ("TGT", "target_hit"),
                     ("MOV", "big_move"), ("ERN", "earnings_soon")}
    assert not any(a["ticker"] == "9988.HK" for a in alerts)  # market closed
    assert state["alerted"]["2026-07-08"]


def test_dedup_same_day():
    holdings = [_holding("MOV")]
    quotes = {"MOV": {"price": 50.0, "change_pct": -6.0}}
    alerts1, state = watcher.check(holdings, {}, quotes, {}, {}, US_OPEN)
    assert len(alerts1) == 1
    alerts2, _ = watcher.check(holdings, {}, quotes, {}, state, US_OPEN)
    assert alerts2 == []                          # same trigger suppressed
    stale = {"alerted": {"2026-07-07": ["MOV:big_move"]}}
    alerts3, state3 = watcher.check(holdings, {}, quotes, {}, stale, US_OPEN)
    assert len(alerts3) == 1                      # new day → fires again
    assert "2026-07-07" not in state3["alerted"]  # old days pruned


def test_escalation_cap_and_trigger_filter():
    alerts = [{"ticker": "A", "trigger": "stop_breach", "text": "x"},
              {"ticker": "B", "trigger": "target_hit", "text": "x"},
              {"ticker": "C", "trigger": "stop_breach", "text": "x"},
              {"ticker": "D", "trigger": "big_move", "text": "x"}]  # not escalatable
    calls = []
    lines, state = watcher.escalate(alerts, {}, US_OPEN,
                                    run_fn=lambda t: calls.append(t) or f"read {t}")
    assert calls == ["A", "B"]                    # cap = 2, D's trigger filtered
    assert len(lines) == 2
    assert state["escalations"]["2026-07-08"] == 2
    # A later run the same day gets nothing more.
    lines2, _ = watcher.escalate(alerts, state, US_OPEN,
                                 run_fn=lambda t: calls.append(t) or "read")
    assert lines2 == [] and calls == ["A", "B"]


def test_escalation_failure_keeps_alerts_flowing():
    def boom(t):
        raise RuntimeError("llm down")
    lines, state = watcher.escalate(
        [{"ticker": "A", "trigger": "stop_breach", "text": "x"}], {}, US_OPEN,
        run_fn=boom)
    assert lines == [] and state["escalations"]["2026-07-08"] == 0


def test_state_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    watcher._save_state({"alerted": {"d": ["x"]}}, file_path=path)
    assert watcher._load_state(path) == {"alerted": {"d": ["x"]}}
    assert watcher._load_state(str(tmp_path / "missing.json")) == {}
