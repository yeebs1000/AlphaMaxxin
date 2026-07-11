"""Conviction ledger: recording, levels map, scoring transitions, summary."""
import datetime

from app.reports import ledger


def _report(recs, blocks, report_id="r1", created="2026-07-01T00:00:00+00:00"):
    return {"id": report_id, "preset": "Lite", "created_at": created,
            "sections": {"skills": {"recommendation_blocks": blocks},
                         "synthesis": {"recommendations": recs}}}


def _block(price=100.0, stop=90.0, target=120.0):
    return {"current_price": price, "bear_stop": stop, "base_target": target}


def test_record_joins_blocks_and_skips_nonactionable(tmp_path):
    path = str(tmp_path / "ledger.json")
    added = ledger.record(_report(
        recs=[{"ticker": "AAA", "action": "buy", "conviction": "high", "size": "Full"},
              {"ticker": "BBB", "action": "hold", "conviction": "high"},   # not a call
              {"ticker": "CCC", "action": "buy", "conviction": "medium"}],  # no block
        blocks={"AAA": _block(), "BBB": _block(50, 45, 60)}), file_path=path)
    assert added == 1
    data = ledger._load(path)
    assert [e["ticker"] for e in data["entries"]] == ["AAA"]
    assert data["entries"][0]["price_at_rec"] == 100.0
    assert data["entries"][0]["status"] == "open"
    # Levels map covers EVERY blocked ticker, hold included.
    assert set(data["levels"]) == {"AAA", "BBB"}
    # Re-recording the same report is idempotent.
    assert ledger.record(_report(
        recs=[{"ticker": "AAA", "action": "buy", "conviction": "high"}],
        blocks={"AAA": _block()}), file_path=path) == 0


def test_score_transitions(tmp_path):
    path = str(tmp_path / "ledger.json")
    ledger.record(_report(
        recs=[{"ticker": "TGT", "action": "buy", "conviction": "high"},
              {"ticker": "STP", "action": "accumulate", "conviction": "medium"},
              {"ticker": "OLD", "action": "buy", "conviction": "low"},
              {"ticker": "SEL", "action": "reduce", "conviction": "high"}],
        blocks={t: _block() for t in ("TGT", "STP", "OLD", "SEL")}), file_path=path)

    quotes = {"TGT": {"price": 125.0}, "STP": {"price": 88.0},
              "OLD": {"price": 101.0}, "SEL": {"price": 95.0}}
    data = ledger.score(lambda t: quotes.get(t), file_path=path,
                        today=datetime.date(2026, 10, 15))  # >90d after 07-01
    st = {e["ticker"]: e["status"] for e in data["entries"]}
    assert st == {"TGT": "target", "STP": "stopped", "OLD": "expired", "SEL": "expired"}
    tgt = next(e for e in data["entries"] if e["ticker"] == "TGT")
    assert tgt["return_pct"] == 25.0 and tgt["resolved_date"] == "2026-10-15"

    s = ledger.summary(file_path=path)
    assert s["by_conviction"]["high"]["target_hits"] == 1     # TGT
    assert s["by_conviction"]["high"]["hit_rate"] == 1.0      # SEL expired, not a stop
    assert s["by_conviction"]["medium"]["hit_rate"] == 0.0    # STP stopped
    assert s["by_conviction"]["low"]["hit_rate"] is None      # expired only
    assert s["open"] == 0 and s["total"] == 4


def test_missing_or_corrupt_file_is_empty(tmp_path):
    assert ledger._load(str(tmp_path / "nope.json")) == {"entries": [], "levels": {}}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert ledger._load(str(bad))["entries"] == []
    assert ledger.summary(file_path=str(bad))["total"] == 0


def test_record_is_failure_soft():
    assert ledger.record(None, file_path="ignored") == 0  # type: ignore[arg-type]
