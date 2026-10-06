"""MCP server: tool registration, read-only annotations, and behavior of the
file-backed and degradable tools — all offline."""
import json

import pytest

from app import mcp_server


@pytest.mark.asyncio
async def test_all_tools_registered_and_read_only():
    tools = await mcp_server.mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {"get_portfolio", "get_ledger", "get_technicals",
                     "get_macro", "get_supply_chain", "get_backtest_results",
                     "get_equity_history", "list_reports", "get_report"}
    for t in tools:
        assert t.annotations.readOnlyHint is True, t.name
        assert t.description, t.name  # every tool documents itself


@pytest.mark.asyncio
async def test_external_feed_tools_declare_open_world_access():
    feed_tools = {"get_portfolio", "get_ledger", "get_technicals",
                  "get_macro", "get_supply_chain"}
    for tool in await mcp_server.mcp.list_tools():
        assert tool.annotations.openWorldHint is (tool.name in feed_tools), tool.name


def test_get_ledger_scores_snapshot_without_changing_stored_bytes(tmp_path, monkeypatch):
    from app.reports import ledger
    from .fakes import make_registry, FakeYahoo

    path = tmp_path / "ledger.json"
    stored = {"entries": [{
        "id": "r1:AAA", "date": "2000-01-01", "ticker": "AAA",
        "action": "buy", "conviction": "high", "price_at_rec": 100,
        "base_target": 120, "bear_stop": 90, "status": "open",
    }], "levels": {"AAA": {"base_target": 120, "bear_stop": 90}}}
    original = json.dumps(stored, indent=2).encode("utf-8")
    path.write_bytes(original)
    monkeypatch.setenv("ALPHAMAXXIN_LEDGER_FILE", str(path))
    registry = make_registry(yahoo=FakeYahoo(quotes={"AAA": {"price": 125}}))
    monkeypatch.setattr(mcp_server, "_registry", lambda: registry)

    result = mcp_server.get_ledger()

    assert result["entries"][0]["status"] == "target"
    assert result["entries"][0]["return_pct"] == 25.0
    assert result["levels"] == stored["levels"]
    assert result["summary"]["open"] == 0
    assert result["summary"]["by_conviction"]["high"]["hit_rate"] == 1.0
    assert path.read_bytes() == original
    assert ledger.summary()["open"] == 1


def test_get_ledger_does_not_create_missing_store(tmp_path, monkeypatch):
    from .fakes import make_registry

    path = tmp_path / "missing-ledger.json"
    monkeypatch.setenv("ALPHAMAXXIN_LEDGER_FILE", str(path))
    monkeypatch.setattr(mcp_server, "_registry", make_registry)

    assert mcp_server.get_ledger() == {
        "entries": [], "levels": {},
        "summary": {"by_conviction": {}, "open": 0, "total": 0},
    }
    assert not path.exists()


def test_backtest_results_reads_file(tmp_path, monkeypatch):
    path = tmp_path / "bt.json"
    path.write_text(json.dumps({"n_events": 42}), encoding="utf-8")
    monkeypatch.setattr(mcp_server, "BACKTEST_FILE", str(path))
    assert mcp_server.get_backtest_results()["n_events"] == 42
    monkeypatch.setattr(mcp_server, "BACKTEST_FILE", str(tmp_path / "missing.json"))
    assert "error" in mcp_server.get_backtest_results()


def test_get_technicals_with_fake_registry(monkeypatch):
    from .fakes import make_registry, FakeYahoo
    closes = [100 + i * 0.1 for i in range(260)]
    bars = {"closes": closes, "highs": [c + 1 for c in closes],
            "lows": [c - 1 for c in closes], "volumes": [1000.0] * 260}
    registry = make_registry(yahoo=FakeYahoo(
        ohlcv_data={"MSFT": bars},
        search_results={"MSFT": [{"symbol": "MSFT", "name": "Microsoft",
                                  "type": "EQUITY"}]}))
    monkeypatch.setattr(mcp_server, "_registry", lambda: registry)
    out = mcp_server.get_technicals("MSFT")
    assert out["snapshot"]["ticker"] == "MSFT"
    assert out["snapshot"]["signal"]["label"]
    assert out["strategy_panel"]["verdicts"]
    assert "error" in mcp_server.get_technicals("NOPE")


def test_get_portfolio_empty_book(monkeypatch):
    from app import portfolio as pf
    monkeypatch.setattr(pf, "parse_portfolio", lambda: [])
    assert "error" in mcp_server.get_portfolio()
