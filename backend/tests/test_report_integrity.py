"""Financial trust boundaries, exercised without providers or model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.llm import analysts
from app.llm.cache import LLMCache
from app.data.base import DiskTTLCache
from app.skills import signals, performance


def test_empty_example_configuration_boots_offline():
    env = dict(os.environ, ALPHAMAXXIN_OFFLINE="1")
    for key in ("MOOMOO_HOST", "MOOMOO_PORT", "IBKR_HOST", "IBKR_PORT", "IBKR_CLIENT_ID"):
        env.pop(key, None)
    code = ("from pathlib import Path; from backend.app.config import load_env; "
            "load_env(Path('.env.example')); from backend.app.main import create_app; "
            "from fastapi.testclient import TestClient; "
            "assert TestClient(create_app(), base_url='http://127.0.0.1:8000').get('/api/status').status_code == 200")
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_missing_fundamentals_do_not_count_as_neutral_evidence():
    snap = {"growth": {"rev_yoy": None}, "margins": {"net": None},
            "analyst": {"target_mean": None}, "quality_flags": [], "price": 100}
    result = signals.aggregate("A", {"signal": {"score": 100}}, snap,
                               {"A": {"count": 1, "avg_score": .5}})
    assert result["components"]["fundamental"] is None
    assert result["coverage"] == .5 and result["conviction"] == "medium"
    assert signals.fundamental_score({"growth": {"rev_yoy": 0}}) == 0


@pytest.mark.parametrize("target,stop,score", [(80, 90, 80), (120, 105, 80),
                                              (120, 90, -80)])
def test_unfavourable_long_setup_cannot_receive_buy_size(target, stop, score):
    block = signals.recommendation_block(
        "A", {"last_close": 100, "atr14": 5}, {"analyst": {"target_mean": target}},
        atr_stop=stop, composite={"conviction": "high", "composite_score": score})
    assert block["size_tier"] == "Pass" and block["suggested_weight_pct"] == 0


def test_missing_fx_is_an_incomplete_valuation():
    summary = performance.portfolio_summary(
        [{"ticker": "HK", "quantity": 10, "cost_price": 50, "currency": "HKD"}],
        {"HK": {"price": 100, "currency": "HKD"}}, {"USD": 1})
    assert summary["errors"] and summary["holdings_count"] == 0


def test_daily_gain_uses_previous_value_not_current_value():
    summary = performance.portfolio_summary(
        [{"ticker": "A", "quantity": 10, "cost_price": 100, "currency": "USD"}],
        {"A": {"price": 200, "currency": "USD", "change_pct": 100}})
    assert summary["day_change_usd"] == 1000


def test_historical_mwr_does_not_backdate_current_quotes(monkeypatch):
    from app import equity_history, health_check
    monkeypatch.setattr(equity_history, "_load", lambda: [
        {"date": "2026-01-01", "value_usd": 1000, "cost_usd": 1000},
        {"date": "2026-01-31", "value_usd": 1000, "cost_usd": 1000}])
    result = health_check.money_weighted(1100, pull_broker=False)
    assert result["mwr_annual_pct"] == 0


def test_sale_excluded_returns_cannot_be_compared_with_full_window_benchmark():
    from app import health_check
    from .fakes import make_registry, FakeYahoo
    registry = make_registry(yahoo=FakeYahoo(ohlcv_data={"^GSPC": {
        "timestamps": ["2026-01-01", "2026-01-31"], "closes": [100, 200]}}))
    assert health_check._benchmark_return(registry, {
        "first_date": "2026-01-01", "last_date": "2026-01-31", "periods_excluded_sales": 1}) is None


def _payload():
    block = signals.recommendation_block(
        "A", {"last_close": 100, "atr14": 5}, {"analyst": {"target_mean": 130}},
        composite={"conviction": "high", "composite_score": 80})
    return {"recommendation_blocks": {"A": block},
            "composites": {"A": {"conviction": "high"}},
            "summary": {"tickers": ["A"]},
            "analysts": [{"ok": True, "stance": "supportive"}] * 3}


async def _synth(payload, rec, cache=None, calls=None):
    async def transport(*args, **kwargs):
        if calls is not None:
            calls.append(1)
        return {"text": json.dumps({"markdown": "# Invented target 999",
                                    "recommendations": [rec]})}
    return await analysts.run_synthesis(payload, "local/test", transport=transport, cache=cache)


@pytest.mark.parametrize("change", [{"ticker": "OUTSIDE"}, {"target": 999},
                                    {"size": "Starter"}, {"action": "magic"}])
async def test_synthesis_rejects_unsupported_recommendations(change):
    rec = {"ticker": "A", "action": "buy", "conviction": "high",
           "size": "Full", "rationale": "test"} | change
    result = await _synth(_payload(), rec)
    assert not result["ok"] and not result["recommendations"]


async def test_synthesis_veto_and_invalid_output_are_not_cached(tmp_path):
    payload = _payload()
    payload["recommendation_blocks"]["A"]["red_lines"] = ["distress"]
    calls = []
    cache = LLMCache(DiskTTLCache(root=tmp_path))
    rec = {"ticker": "A", "action": "buy", "conviction": "high", "size": "Full"}
    for _ in range(2):
        result = await _synth(payload, rec, cache, calls)
        assert not result["ok"]
    assert len(calls) == 2


async def test_incomplete_portfolio_valuation_vetoes_buy_allocation():
    payload = _payload()
    payload["summary"]["errors"] = ["no price for missing holding"]
    result = await _synth(payload, {"ticker": "A", "action": "buy", "conviction": "high", "size": "Full"})
    assert not result["ok"] and not result["recommendations"]


async def test_report_numbers_are_rendered_from_computed_blocks():
    result = await _synth(_payload(), {"ticker": "A", "action": "buy",
                         "conviction": "high", "size": "Full", "rationale": "test"})
    assert result["ok"]
    assert "999" not in result["markdown"]
    assert "130" in result["markdown"] and "90" in result["markdown"]


def test_unverified_commentary_is_separate_and_html_escaped():
    from app.reports.render import render_report_html
    html = render_report_html("Demo", "# Computed table", commentary_md='<script>alert(1)</script>')
    assert '<details>' in html and 'Unverified model commentary' in html
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html


@pytest.mark.parametrize("body", [[], True, {"narrative_md": ["bad"]}])
async def test_invalid_analyst_shape_fails_soft(body):
    async def transport(*args, **kwargs):
        return {"text": json.dumps(body)}
    result = await analysts.run_analyst("risk", {}, "local/test", transport=transport)
    assert not result["ok"]


def test_context_refuses_calendarless_mismatched_arrays():
    from app.skills import portfolio_context
    a = [.01, -.02] * 120
    assert portfolio_context.beta(a, a[1:]) is None
    assert portfolio_context.correlation(a, a[1:]) is None


def test_foreign_currency_turnover_uses_same_units_as_position():
    from app.reports import pipeline
    from .fakes import make_registry, FakeYahoo
    bars = {"closes": [100.] * 30, "highs": [101.] * 30, "lows": [99.] * 30,
            "volumes": [1000] * 30, "timestamps": [f"2026-09-{i:02}" for i in range(1, 31)]}
    reg = make_registry(yahoo=FakeYahoo(ohlcv_data={"HK": bars},
                        quotes={"HK": {"price": 100, "currency": "HKD"}}, fx={"HKD": .128}))
    result = pipeline.run_skills(reg, {"skills": ["technicals", "risk"]},
                [{"ticker": "HK", "quantity": 1000, "currency": "HKD"}], lambda *args: None)
    assert result["risk"]["liquidity"]["days_to_liquidate_10pct"]["HK"] == 10
