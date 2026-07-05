"""Order book skill (moomoo Level 2): summary math, graceful degradation,
and the pipeline's skip-when-empty behavior for the promoted lens."""
import json

import pytest

from app.skills import order_book
from app.reports.pipeline import run_report
from app.reports import store
from app import portfolio as pf
from .fakes import make_registry, FakeYahoo, FakeYFinance

BOOK = {
    "code": "US.MSFT",
    "bids": [{"price": 399.90, "volume": 500}, {"price": 399.85, "volume": 800}],
    "asks": [{"price": 400.10, "volume": 300}, {"price": 400.15, "volume": 400}],
}


def test_summarize_depth_math():
    s = order_book.summarize_depth(BOOK)
    assert s["best_bid"] == 399.90 and s["best_ask"] == 400.10
    assert s["spread"] == pytest.approx(0.20)
    assert s["spread_bps"] == pytest.approx(0.20 / 400.0 * 10000, abs=0.1)
    assert s["bid_depth"] == 1300 and s["ask_depth"] == 700
    assert s["imbalance"] == pytest.approx(1300 / 2000)
    assert s["levels"] == 2


def test_summarize_depth_degrades():
    assert order_book.summarize_depth(None) is None
    assert order_book.summarize_depth({"bids": [], "asks": []}) is None


def test_fetch_depth_summaries_offline_returns_empty():
    # Under ALPHAMAXXIN_OFFLINE the moomoo chokepoint raises; the skill must
    # swallow that into "no data", never propagate or invent.
    assert order_book.fetch_depth_summaries(["MSFT"]) == {}


def test_fetch_depth_summaries_with_mocked_moomoo(monkeypatch):
    from app.brokers import moomoo_client
    monkeypatch.setattr(moomoo_client, "MOOMOO_AVAILABLE", True)
    monkeypatch.setattr(moomoo_client, "get_moomoo_orderbook",
                        lambda t, depth=10: BOOK if t == "MSFT" else None)
    out = order_book.fetch_depth_summaries(["MSFT", "01810"])
    assert "MSFT" in out and "01810" not in out  # unentitled ticker just absent


def _bars(start, end, n=260):
    closes = [start + (end - start) * i / (n - 1) for i in range(n)]
    return {"closes": closes, "highs": [c + 1 for c in closes],
            "lows": [c - 1 for c in closes], "volumes": [1000] * n}


async def test_portfolio_medic_runs_order_book_lens(tmp_path, monkeypatch):
    from app.brokers import moomoo_client
    from app.data import registry as registry_mod
    monkeypatch.setattr(moomoo_client, "MOOMOO_AVAILABLE", True)
    monkeypatch.setattr(moomoo_client, "get_moomoo_orderbook",
                        lambda t, depth=10: BOOK)
    monkeypatch.setattr(registry_mod, "_orderbook_feed_up", lambda: True)

    path = str(tmp_path / "Portfolio.md")
    monkeypatch.setattr(pf, "PORTFOLIO_FILE", path)
    pf.save_portfolio([{"company": "Microsoft", "ticker": "MSFT",
                        "quantity": 10, "cost_price": 380.0, "currency": "USD"}],
                      file_path=path)

    calls = []

    async def transport(system_prompt, user_prompt, model):
        calls.append(system_prompt[:40])
        if "Order Book" in system_prompt:
            assert '"spread"' in user_prompt  # real depth summary reached the lens
        body = ({"markdown": "# R", "recommendations": []}
                if "Synthesis" in system_prompt else
                {"stance": "neutral", "confidence": "medium",
                 "key_findings": ["f"], "narrative_md": "n"})
        return {"text": json.dumps(body), "model": model,
                "in_tokens": 100, "out_tokens": 50}

    registry = make_registry(
        yahoo=FakeYahoo(ohlcv_data={"MSFT": _bars(300, 400), "^GSPC": _bars(5000, 5800)},
                        quotes={"MSFT": {"price": 400.0, "currency": "USD", "change_pct": 1.0},
                                "^GSPC": {"price": 5800.0, "currency": "USD", "change_pct": 0.5}},
                        search_results={"MSFT": [{"symbol": "MSFT", "name": "Microsoft",
                                                  "type": "EQUITY"}]}),
        yfinance=FakeYFinance(fundamentals={"MSFT": {"ticker": "MSFT", "price": 400.0,
                                                     "target_mean": 480.0}}))
    report_id = await run_report(registry, {"preset": "Portfolio Medic",
                                            "target": {"kind": "portfolio"}},
                                 lambda *a, **k: None,
                                 reports_dir=str(tmp_path / "reports"),
                                 transport=transport)
    report = store.load_report(report_id, str(tmp_path / "reports"))
    assert "order_book" in report["sections"]["analysts"]
    assert report["sections"]["skills"]["order_book"]["MSFT"]["spread"] == pytest.approx(0.20)


async def test_order_book_lens_skipped_when_no_depth(tmp_path, monkeypatch):
    """Feed up but zero tickers returned depth → the analyst call is skipped
    entirely instead of billing a lens whose whole input is 'no data'."""
    from app.brokers import moomoo_client
    from app.data import registry as registry_mod
    monkeypatch.setattr(moomoo_client, "MOOMOO_AVAILABLE", True)
    monkeypatch.setattr(moomoo_client, "get_moomoo_orderbook", lambda t, depth=10: None)
    monkeypatch.setattr(registry_mod, "_orderbook_feed_up", lambda: True)

    path = str(tmp_path / "Portfolio.md")
    monkeypatch.setattr(pf, "PORTFOLIO_FILE", path)
    pf.save_portfolio([{"company": "Microsoft", "ticker": "MSFT",
                        "quantity": 10, "cost_price": 380.0, "currency": "USD"}],
                      file_path=path)

    roles_called = []

    async def transport(system_prompt, user_prompt, model):
        roles_called.append(system_prompt[:40])
        body = ({"markdown": "# R", "recommendations": []}
                if "Synthesis" in system_prompt else
                {"stance": "neutral", "confidence": "medium",
                 "key_findings": ["f"], "narrative_md": "n"})
        return {"text": json.dumps(body), "model": model,
                "in_tokens": 100, "out_tokens": 50}

    registry = make_registry(
        yahoo=FakeYahoo(ohlcv_data={"MSFT": _bars(300, 400), "^GSPC": _bars(5000, 5800)},
                        quotes={"MSFT": {"price": 400.0, "currency": "USD", "change_pct": 1.0}},
                        search_results={"MSFT": [{"symbol": "MSFT", "name": "Microsoft",
                                                  "type": "EQUITY"}]}))
    report_id = await run_report(registry, {"preset": "Portfolio Medic",
                                            "target": {"kind": "portfolio"}},
                                 lambda *a, **k: None,
                                 reports_dir=str(tmp_path / "reports"),
                                 transport=transport)
    report = store.load_report(report_id, str(tmp_path / "reports"))
    assert "order_book" not in report["sections"]["analysts"]
    assert not any("Order Book" in r for r in roles_called)
