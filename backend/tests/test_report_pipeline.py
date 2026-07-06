"""Mocked end-to-end pipeline runs: fixture data in, canned LLM JSON out,
artifacts on disk, lens transparency preserved."""
import json

import pytest

from app.llm.costs import CostMeter
from app.reports import store
from app.reports.pipeline import run_report, resolve_target
from app.reports.presets import get_preset, list_presets, PRESETS
from app.reports.render import render_report_html
from app import watchlists as wl
from .fakes import make_registry, FakeYahoo, FakeFinnhub, FakeYFinance


def _bars(start, end, n=260):
    closes = [start + (end - start) * i / (n - 1) for i in range(n)]
    return {"closes": closes, "highs": [c + 1 for c in closes],
            "lows": [c - 1 for c in closes], "volumes": [1000] * n}


def _registry():
    quotes = {"MSFT": {"price": 400.0, "currency": "USD", "change_pct": 1.0},
              "^GSPC": {"price": 5800.0, "currency": "USD", "change_pct": 0.5}}
    return make_registry(
        yahoo=FakeYahoo(
            ohlcv_data={"MSFT": _bars(300, 400), "^GSPC": _bars(5000, 5800)},
            quotes=quotes,
            search_results={"MSFT": [{"symbol": "MSFT", "name": "Microsoft",
                                      "type": "EQUITY"}]}),
        finnhub=FakeFinnhub(earnings=[{"date": "2026-07-10", "symbol": "MSFT",
                                       "epsEstimate": 2.9}]),
        yfinance=FakeYFinance(fundamentals={"MSFT": {
            "ticker": "MSFT", "name": "Microsoft", "pe_ttm": 30.0,
            "rev_yoy": 0.12, "net_margin": 0.35, "price": 400.0,
            "target_mean": 480.0, "sector": "Technology"}}),
    )


def canned_transport(calls):
    async def transport(system_prompt, user_prompt, model):
        calls.append({"system": system_prompt[:60], "model": model})
        if "Synthesis" in system_prompt:
            body = {"markdown": "# Report\n\n## Verdict\nHold MSFT.",
                    "recommendations": [{"ticker": "MSFT", "action": "hold",
                                         "conviction": "medium", "rationale": "mixed"}]}
        else:
            body = {"stance": "neutral", "confidence": "medium",
                    "key_findings": ["finding"], "narrative_md": "Narrative."}
        return {"text": json.dumps(body), "model": model,
                "in_tokens": 2000, "out_tokens": 300}
    return transport


@pytest.fixture
def portfolio_target(tmp_path, monkeypatch):
    from app import portfolio as pf
    path = str(tmp_path / "Portfolio.md")
    monkeypatch.setattr(pf, "PORTFOLIO_FILE", path)
    pf.save_portfolio([{"company": "Microsoft", "ticker": "MSFT",
                        "quantity": 10, "cost_price": 380.0, "currency": "USD"}],
                      file_path=path)
    return path


async def test_lite_run_end_to_end(tmp_path, portfolio_target):
    calls, events = [], []
    meter = CostMeter(str(tmp_path / "costs.json"))
    report_id = await run_report(
        _registry(), {"preset": "Lite", "target": {"kind": "portfolio"}},
        lambda stage, msg, pct, role=None: events.append(stage),
        meter=meter, run_id="r1", reports_dir=str(tmp_path / "reports"),
        transport=canned_transport(calls))

    # Right lenses ran: Lite = fundamentals, technicals_options, risk + synthesis
    assert len(calls) == 4
    # Artifacts on disk + indexed
    report = store.load_report(report_id, str(tmp_path / "reports"))
    assert report["preset"] == "Lite"
    assert set(report["sections"]["analysts"]) == \
        {"fundamentals", "technicals_options", "risk"}
    assert report["sections"]["synthesis"]["recommendations"][0]["ticker"] == "MSFT"
    assert report["sections"]["skills"]["technicals"]["MSFT"]["last_close"] == 400.0
    # recommendation_blocks computed from real technicals+fundamentals (analyst
    # target_mean=480 from the fixture) and reached the technicals_options payload
    reco = report["sections"]["skills"]["recommendation_blocks"]["MSFT"]
    assert reco["bull_target"] == 480.0
    assert reco["target_source"] == "analyst consensus"
    assert report["costs"]["calls"] == 4
    html = store.load_report_html(report_id, str(tmp_path / "reports"))
    assert "Verdict" in html
    index = store.list_reports(str(tmp_path / "reports"))
    assert index[0]["id"] == report_id
    assert "fetch" in events and "synthesis" in events

    # Disabled lenses recorded, never billed
    lenses = {l["id"]: l for l in report["lens_status"]}
    assert lenses["order_book"]["enabled"] is False
    assert lenses["ml_alpha"]["enabled"] is False


async def test_synthesis_failure_falls_back_to_analyst_narratives(tmp_path, portfolio_target):
    """A failed synthesis call must never produce a blank report — the
    fallback assembles whatever analysts succeeded, and names why."""
    async def flaky_transport(system_prompt, user_prompt, model):
        if "Synthesis" in system_prompt:
            return {"text": "not json at all", "model": model, "in_tokens": 5,
                    "out_tokens": 5, "error": "Claude API call failed: 529 overloaded"}
        return {"text": json.dumps({"stance": "neutral", "confidence": "medium",
                                    "key_findings": ["f"], "narrative_md": "All good."}),
                "model": model, "in_tokens": 100, "out_tokens": 50}

    report_id = await run_report(
        _registry(), {"preset": "Lite", "target": {"kind": "portfolio"}},
        lambda *a, **k: None, reports_dir=str(tmp_path / "reports"),
        transport=flaky_transport)
    report = store.load_report(report_id, str(tmp_path / "reports"))
    synthesis = report["sections"]["synthesis"]
    assert synthesis["ok"] is False
    assert "529 overloaded" in synthesis["markdown"]
    assert "All good." in synthesis["markdown"]  # surviving analyst narrative included
    html = store.load_report_html(report_id, str(tmp_path / "reports"))
    assert "529 overloaded" in html  # visible in the rendered page, not just JSON


async def test_ticker_target_run(tmp_path):
    calls = []
    report_id = await run_report(
        _registry(), {"preset": "Lite", "target": {"kind": "tickers",
                                                   "tickers": ["MSFT"]}},
        lambda *a, **k: None, reports_dir=str(tmp_path / "reports"),
        transport=canned_transport(calls))
    report = store.load_report(report_id, str(tmp_path / "reports"))
    assert report["target_label"] == "MSFT"


async def test_watchlist_target_run(tmp_path, monkeypatch):
    monkeypatch.setattr(wl, "WATCHLISTS_FILE", str(tmp_path / "wl.json"))
    created = wl.create_watchlist("Tech", ["MSFT"])
    calls = []
    report_id = await run_report(
        _registry(), {"preset": "Lite",
                      "target": {"kind": "watchlist", "watchlist_id": created["id"]}},
        lambda *a, **k: None, reports_dir=str(tmp_path / "reports"),
        transport=canned_transport(calls))
    report = store.load_report(report_id, str(tmp_path / "reports"))
    assert "Tech" in report["target_label"]


async def test_empty_portfolio_raises(tmp_path, monkeypatch):
    from app import portfolio as pf
    monkeypatch.setattr(pf, "PORTFOLIO_FILE", str(tmp_path / "missing.md"))
    with pytest.raises(ValueError, match="no target tickers"):
        await run_report(_registry(), {"preset": "Lite"}, lambda *a, **k: None,
                         reports_dir=str(tmp_path / "reports"),
                         transport=canned_transport([]))


def test_all_presets_reference_valid_lenses_and_skills():
    from app.llm.analysts import ANALYSTS
    valid_skills = {"technicals", "fundamentals", "macro", "risk", "news",
                    "catalysts", "screener", "signals", "performance",
                    "portfolio_construction", "options_math", "politician_trades",
                    "order_book", "ml_alpha"}
    assert len(PRESETS) == 10  # Lite + the 9 full v1 presets
    for preset in list_presets():
        assert set(preset["analysts"]) <= set(ANALYSTS)
        assert set(preset["skills"]) <= valid_skills
    assert get_preset("Dragon Watch")["regions"] == ["HK"]
    with pytest.raises(KeyError):
        get_preset("Nonexistent")


def test_store_delete(tmp_path):
    rid = store.save_report({"preset": "Lite", "target_label": "X",
                             "created_at": "now", "sections": {}},
                            reports_dir=str(tmp_path))
    assert store.delete_report(rid, str(tmp_path)) is True
    assert store.load_report(rid, str(tmp_path)) is None
    assert store.list_reports(str(tmp_path)) == []


def test_render_tables_and_headers():
    md = "# Title\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n- Point one\nScore: 42"
    html = render_report_html("T — MSFT", md)
    assert "<table>" in html and "<th>A</th>" in html and "<td>1</td>" in html
    assert "<h1>Title</h1>" in html
    assert "<strong>Score:</strong>" in html
    assert "not financial advice" in html
    assert "Georgia" in html                    # serif headline font stack
    assert '<img class="logo"' in html           # single-ticker gets a logo


def test_render_no_logo_for_portfolio_target():
    html = render_report_html("Lite — Portfolio", "# Report\nbody")
    assert '<img class="logo"' not in html
