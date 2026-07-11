"""Daily digest: message formatting, non-trading-day skip, send path — all
offline (fake sender, no pipeline run, no network)."""
from datetime import datetime, timezone

import app.digest as digest

_WEEKDAY = datetime(2026, 7, 10, 21, 0, tzinfo=timezone.utc)  # a Friday


def _report(recs):
    return {"sections": {"synthesis": {"recommendations": recs}}}


def test_build_message_filters_and_formats():
    reports = {
        "Opportunist": _report([
            {"ticker": "RBLX", "action": "buy", "conviction": "high",
             "size": "Half", "rationale": "momentum + upgrade"},
            {"ticker": "XYZ", "action": "hold", "conviction": "low"}]),   # hold → dropped
        "Portfolio Medic": _report([
            {"ticker": "C6L", "action": "reduce", "conviction": "medium",
             "rationale": "above target"},
            {"ticker": "MSFT", "action": "hold", "conviction": "high"}]),  # hold not a trim
    }
    msg = digest.build_message(reports, now=_WEEKDAY)
    assert "RBLX — buy" in msg and "XYZ" not in msg          # only buy/accumulate as ideas
    assert "C6L — reduce" in msg and "MSFT" not in msg       # only reduce/sell as watch-outs
    assert "Worth noting" in msg and "Look out for" in msg


def test_build_message_handles_missing_reports():
    msg = digest.build_message({"Opportunist": None, "Portfolio Medic": None}, now=_WEEKDAY)
    assert "no high-conviction ideas" in msg and "nothing flagged" in msg


def test_build_message_ledger_line_only_when_resolved():
    summary = {"by_conviction": {
        "high": {"resolved": 13, "hit_rate": 0.62},
        "medium": {"resolved": 0, "hit_rate": None}}}
    msg = digest.build_message({}, now=_WEEKDAY, ledger_summary=summary)
    assert "📒 Ledger: high 62% hit (13 resolved)" in msg
    assert "medium" not in msg                       # nothing resolved → omitted
    assert "Ledger" not in digest.build_message({}, now=_WEEKDAY)  # no summary


def test_run_digest_skips_non_trading_day(monkeypatch):
    monkeypatch.setattr(digest.cal, "is_trading_day", lambda *a, **k: False)
    sent = []
    assert digest.run_digest(sender=sent.append) is None
    assert sent == []                                        # nothing pushed on a weekend


def test_run_digest_sends_on_trading_day(monkeypatch):
    monkeypatch.setattr(digest.cal, "is_trading_day", lambda *a, **k: True)

    async def fake_run(preset):
        return _report([{"ticker": "AAA", "action": "buy", "conviction": "high",
                         "size": "Full", "rationale": "x"}])
    monkeypatch.setattr(digest, "_run_preset", fake_run)

    sent = []
    msg = digest.run_digest(presets=("Opportunist",), sender=sent.append)
    assert sent and "AAA — buy" in sent[0] and msg == sent[0]


def test_run_digest_syncs_brokers_only_for_portfolio_medic(monkeypatch):
    monkeypatch.setattr(digest.cal, "is_trading_day", lambda *a, **k: True)

    async def fake_run(preset):
        return _report([])
    monkeypatch.setattr(digest, "_run_preset", fake_run)
    calls = []
    monkeypatch.setattr(digest.pf, "sync_from_brokers",
                        lambda *a, **k: (calls.append(1), {"success": True})[1])

    digest.run_digest(presets=("Opportunist",), sender=lambda m: None)
    assert calls == []                                  # no holdings preset → no sync
    digest.run_digest(presets=("Portfolio Medic",), sender=lambda m: None)
    assert calls == [1]                                 # holdings preset → live broker sync
