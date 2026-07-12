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