"""Portfolio.md parse/save round-trip, broker merge math, and sync flow with
all brokers mocked (never a live connection in tests)."""
import json

import pytest

from app import portfolio as pf

HOLDINGS = [
    {"company": "Microsoft", "ticker": "MSFT", "quantity": 2.0,
     "cost_price": 385.985, "currency": "USD"},
    {"company": "Grab Holdings", "ticker": "GRAB", "quantity": 100.0,
     "cost_price": 3.32, "currency": "USD"},
    {"company": "DBS", "ticker": "D05", "quantity": 50.0,
     "cost_price": 38.05, "currency": "SGD"},
    {"company": "XIAOMI-W", "ticker": "01810", "quantity": 100.0,
     "cost_price": 23.68, "currency": "HKD"},
]


def test_save_parse_round_trip(tmp_path):
    path = str(tmp_path / "Portfolio.md")
    pf.save_portfolio(HOLDINGS, file_path=path,
                      quotes={"MSFT": {"price": 400.0}})
    parsed = pf.parse_portfolio(path)
    assert len(parsed) == 4
    by_ticker = {h["ticker"]: h for h in parsed}
    assert by_ticker["MSFT"]["quantity"] == 2.0
    assert by_ticker["MSFT"]["cost_price"] == pytest.approx(385.985)
    assert by_ticker["MSFT"]["currency"] == "USD"
    assert by_ticker["D05"]["currency"] == "SGD"
    assert by_ticker["01810"]["currency"] == "HKD"
    assert by_ticker["GRAB"]["quantity"] == 100.0


def test_save_falls_back_to_cost_without_quote(tmp_path):
    path = str(tmp_path / "Portfolio.md")
    pf.save_portfolio([HOLDINGS[0]], file_path=path)  # no quotes at all
    content = open(path, encoding="utf-8").read()
    assert "385.985" in content  # cost shown as current price too
    assert "+0.00" in content    # zero P/L at cost


def test_parse_missing_file_returns_empty(tmp_path):
    assert pf.parse_portfolio(str(tmp_path / "nope.md")) == []


def test_merge_holding_weighted_average():
    merged = {}
    pf.merge_holding(merged, "MSFT", "Microsoft", 1, 300.0, "USD")
    pf.merge_holding(merged, "MSFT", "Microsoft", 9, 400.0, "USD")
    h = merged["MSFT"]
    assert h["quantity"] == 10
    assert h["cost_price"] == pytest.approx(390.0)  # (1*300 + 9*400)/10


def test_load_external_holdings(tmp_path):
    path = tmp_path / "external.json"
    path.write_text(json.dumps({"EX": {"quantity": 10, "cost_price": 25.5,
                                       "currency": "USD", "broker": "Robinhood"}}))
    assert pf.load_external_holdings(str(path))["EX"]["quantity"] == 10
    assert pf.load_external_holdings(str(tmp_path / "missing.json")) == {}


def _patch_brokers(monkeypatch, moomoo=None, ibkr=None, tiger=None):
    """Force every broker client into a known state — tests never connect."""
    from app.brokers import moomoo_client, ibkr_client, tiger_client
    monkeypatch.setattr(moomoo_client, "MOOMOO_AVAILABLE", moomoo is not None)
    monkeypatch.setattr(moomoo_client, "get_moomoo_positions", lambda: moomoo)
    monkeypatch.setattr(ibkr_client, "IBKR_AVAILABLE", ibkr is not None)
    monkeypatch.setattr(ibkr_client, "get_ibkr_positions", lambda: ibkr)
    monkeypatch.setattr(tiger_client, "TIGER_AVAILABLE", tiger is not None)
    monkeypatch.setattr(tiger_client, "get_tiger_positions", lambda: tiger)


def test_sync_merges_across_brokers(tmp_path, monkeypatch):
    _patch_brokers(
        monkeypatch,
        moomoo=[{"code": "US.MSFT", "name": "Microsoft", "qty": 1, "average_cost": 300.0},
                {"code": "HK.01810", "name": "XIAOMI-W", "qty": 100, "average_cost": 23.68}],
        ibkr=[{"ticker": "MSFT", "company": "Microsoft", "quantity": 9,
               "cost_price": 400.0, "currency": "USD"}],
    )
    ext = tmp_path / "external.json"
    ext.write_text(json.dumps({"EX": {"quantity": 10, "cost_price": 25.5,
                                      "currency": "USD"}}))
    out_file = str(tmp_path / "Portfolio.md")
    result = pf.sync_from_brokers(external_path=str(ext), file_path=out_file)
    assert result["success"] is True
    by_ticker = {h["ticker"]: h for h in result["holdings"]}
    assert by_ticker["MSFT"]["quantity"] == 10
    assert by_ticker["MSFT"]["cost_price"] == pytest.approx(390.0)
    assert by_ticker["01810"]["currency"] == "HKD"   # market → ccy mapping
    assert by_ticker["EX"]["quantity"] == 10
    # File written and parseable
    assert len(pf.parse_portfolio(out_file)) == 3


def test_sync_no_brokers_configured(tmp_path, monkeypatch):
    _patch_brokers(monkeypatch)  # all unavailable
    result = pf.sync_from_brokers(external_path=str(tmp_path / "none.json"),
                                  file_path=str(tmp_path / "p.md"))
    assert result["success"] is False
    assert "No broker configured" in result["error"]


def test_sync_brokers_unreachable(tmp_path, monkeypatch):
    from app.brokers import moomoo_client, ibkr_client, tiger_client
    monkeypatch.setattr(moomoo_client, "MOOMOO_AVAILABLE", True)
    monkeypatch.setattr(moomoo_client, "get_moomoo_positions", lambda: None)  # reachable=no
    monkeypatch.setattr(ibkr_client, "IBKR_AVAILABLE", False)
    monkeypatch.setattr(tiger_client, "TIGER_AVAILABLE", False)
    result = pf.sync_from_brokers(external_path=str(tmp_path / "none.json"),
                                  file_path=str(tmp_path / "p.md"))
    assert result["success"] is False
    assert "Could not reach" in result["error"]
