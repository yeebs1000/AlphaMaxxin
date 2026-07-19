"""Daily digest: message formatting, non-trading-day skip, send path — all
offline (fake sender, no pipeline run, no network)."""
from datetime import datetime, timezone

import app.digest as digest

_WEEKDAY = datetime(2026, 7, 10, 21, 0, tzinfo=timezone.utc)  # a Friday


def _report(recs):
    return {"sections": {"synthesis": {"recommendations": recs}}}


def test_build_opportunist_message_filters_and_formats():
    report = _report([
        {"ticker": "RBLX", "action": "buy", "conviction": "high",
         "size": "Half", "rationale": "momentum + upgrade"},
        {"ticker": "XYZ", "action": "hold", "conviction": "low"}])   # hold → dropped
    msg = digest.build_opportunist_message(report, now=_WEEKDAY)
    assert "RBLX — buy" in msg and "XYZ" not in msg          # only buy/accumulate as ideas
    assert "Worth noting" in msg


def test_build_portfolio_medic_message_filters_and_formats():
    report = _report([
        {"ticker": "C6L", "action": "reduce", "conviction": "medium",
         "rationale": "above target"},
        {"ticker": "MSFT", "action": "hold", "conviction": "high"}])  # hold not a trim
    msg = digest.build_portfolio_medic_message(report, now=_WEEKDAY)
    assert "C6L — reduce" in msg and "MSFT" not in msg       # only reduce/sell as watch-outs
    assert "Look out for" in msg


def test_build_message_handles_missing_reports():
    assert "no high-conviction ideas" in digest.build_opportunist_message(None, now=_WEEKDAY)
    assert "nothing flagged" in digest.build_portfolio_medic_message(None, now=_WEEKDAY)


def test_build_message_ledger_line_only_when_resolved():
    summary = {"by_conviction": {
        "high": {"resolved": 13, "hit_rate": 0.62},
        "medium": {"resolved": 0, "hit_rate": None}}}
    msg = digest.build_portfolio_medic_message(None, ledger_summary=summary, now=_WEEKDAY)
    assert "📒 Ledger: high 62% hit (13 resolved)" in msg
    assert "medium" not in msg                       # nothing resolved → omitted
    assert "Ledger" not in digest.build_portfolio_medic_message(None, now=_WEEKDAY)  # no summary


def test_build_quant_message_filters_and_formats():
    report = _report([
        {"ticker": "NVDA", "action": "accumulate", "conviction": "high",
         "size": "Half", "rationale": "options skew + ML alpha agree"},
        {"ticker": "XYZ", "action": "hold", "conviction": "low"}])
    msg = digest.build_quant_message(report, now=_WEEKDAY)
    assert "NVDA — accumulate" in msg and "XYZ" not in msg
    assert "Quant Lab" in msg
    assert "nothing quant-flagged" in digest.build_quant_message(None, now=_WEEKDAY)


def test_run_digest_weekly_quant_sends_to_its_own_topic(monkeypatch):
    monkeypatch.setattr(digest.cal, "is_trading_day", lambda *a, **k: True)

    async def fake_run(preset):
        return _report([{"ticker": "AMD", "action": "buy", "conviction": "medium",
                         "size": "Starter", "rationale": "y"}])
    monkeypatch.setattr(digest, "_run_preset", fake_run)

    sent = []
    messages = digest.run_digest(presets=digest._WEEKLY_PRESETS,
                                 sender=lambda m, topic: sent.append((m, topic)))
    assert sent and sent[0][1] == "quant_lab"
    assert messages["Quant Lab"] == sent[0][0]


def test_run_digest_skips_non_trading_day(monkeypatch):
    monkeypatch.setattr(digest.cal, "is_trading_day", lambda *a, **k: False)
    sent = []
    assert digest.run_digest(sender=lambda m, topic: sent.append((m, topic))) is None
    assert sent == []                                        # nothing pushed on a weekend


def test_run_digest_sends_on_trading_day(monkeypatch):
    monkeypatch.setattr(digest.cal, "is_trading_day", lambda *a, **k: True)

    async def fake_run(preset):
        return _report([{"ticker": "AAA", "action": "buy", "conviction": "high",
                         "size": "Full", "rationale": "x"}])
    monkeypatch.setattr(digest, "_run_preset", fake_run)

    sent = []
    messages = digest.run_digest(presets=("Opportunist",),
                                 sender=lambda m, topic: sent.append((m, topic)))
    assert sent and "AAA — buy" in sent[0][0] and sent[0][1] == "opportunist"
    assert messages["Opportunist"] == sent[0][0]


def test_run_digest_syncs_brokers_only_for_portfolio_medic(monkeypatch):
    monkeypatch.setattr(digest.cal, "is_trading_day", lambda *a, **k: True)

    async def fake_run(preset):
        return _report([])
    monkeypatch.setattr(digest, "_run_preset", fake_run)
    calls = []
    monkeypatch.setattr(digest.pf, "sync_from_brokers",
                        lambda *a, **k: (calls.append(1), {"success": True})[1])

    digest.run_digest(presets=("Opportunist",), sender=lambda m, topic: None)
    assert calls == []                                  # no holdings preset → no sync
    digest.run_digest(presets=("Portfolio Medic",), sender=lambda m, topic: None)
    assert calls == [1]                                 # holdings preset → live broker sync
