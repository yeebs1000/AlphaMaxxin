"""Core API endpoints via TestClient, fake registry, tmp file paths — no
network, and never the user's real Portfolio.md / watchlists."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.api.deps import get_registry
from app import portfolio as pf
from app import watchlists as wl
from .fakes import make_registry, FakeYahoo, FakeAlphaVantage


def _bars(start, end, n=260):
    closes = [start + (end - start) * i / (n - 1) for i in range(n)]
    return {"timestamps": list(range(n)), "closes": closes,
            "highs": [c + 1 for c in closes], "lows": [c - 1 for c in closes],
            "volumes": [1000] * n}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "PORTFOLIO_FILE", str(tmp_path / "Portfolio.md"))
    monkeypatch.setattr(wl, "WATCHLISTS_FILE", str(tmp_path / "watchlists.json"))
    app = create_app()
    yahoo = FakeYahoo(
        ohlcv_data={"MSFT": _bars(300, 400), "MSFT:1wk": None},
        quotes={"MSFT": {"price": 400.0, "name": "Microsoft", "ticker": "MSFT",
                         "yahoo_symbol": "MSFT", "currency": "USD",
                         "previous_close": 395.0, "change_pct": 1.27},
                "^GSPC": {"price": 5800.0, "currency": "USD", "change_pct": 0.5}},
        search_results={"MSFT": [{"symbol": "MSFT", "name": "Microsoft", "type": "EQUITY"}],
                        "micro": [{"symbol": "MSFT", "name": "Microsoft", "type": "EQUITY"}]},
        fx={"USD": 1.0, "SGD": 0.75},
    )
    av = FakeAlphaVantage({"MSFT": [
        {"title": "MSFT beats earnings", "url": "https://x.test/1", "source": "T",
         "published_epoch": 100, "published_rel": "1h ago", "ticker": "MSFT",
         "summary": "", "sentiment": "bullish", "sentiment_score": 0.6,
         "provider": "alphavantage"}]})
    app.dependency_overrides[get_registry] = lambda: make_registry(yahoo=yahoo,
                                                                   alphavantage=av)
    return TestClient(app)


def test_status(client):
    body = client.get("/api/status").json()
    assert body["version"].startswith("2.")
    assert body["feeds"]["yahoo"] is True
    assert set(body["brokers"]) == {"moomoo", "ibkr", "tiger"}
    assert "llm" in body["keys"]
    # Every broker reports connected + a human-readable reason when not —
    # a bare true/false gave no way to tell "package missing" from
    # "gateway not running" apart.
    for broker in body["brokers"].values():
        assert "connected" in broker and "reason" in broker
        if not broker["connected"]:
            assert broker["reason"]


def test_portfolio_put_then_get(client):
    holdings = [{"company": "Microsoft", "ticker": "MSFT", "quantity": 2,
                 "cost_price": 385.985, "currency": "USD"}]
    put = client.put("/api/portfolio", json=holdings)
    assert put.status_code == 200
    got = client.get("/api/portfolio").json()["holdings"]
    assert got[0]["ticker"] == "MSFT"
    assert got[0]["cost_price"] == pytest.approx(385.985)


def test_portfolio_summary(client):
    client.put("/api/portfolio", json=[
        {"company": "Microsoft", "ticker": "MSFT", "quantity": 2,
         "cost_price": 385.985, "currency": "USD"}])
    s = client.get("/api/portfolio/summary").json()
    assert s["total_value_usd"] == pytest.approx(800.0)
    assert s["benchmark"]["price"] == 5800.0


def test_portfolio_guidance(client):
    client.put("/api/portfolio", json=[
        {"company": "Microsoft", "ticker": "MSFT", "quantity": 2,
         "cost_price": 385.985, "currency": "USD"}])
    rows = client.get("/api/portfolio/guidance").json()["guidance"]
    assert rows[0]["ticker"] == "MSFT"
    assert rows[0]["pl_pct"] == pytest.approx((400 - 385.985) / 385.985 * 100)
    assert rows[0]["label"] in ("strong buy", "buy", "hold", "sell", "strong sell")


def test_watchlist_crud(client):
    created = client.post("/api/watchlists",
                          json={"name": "AI names", "tickers": ["msft", "NVDA", "MSFT"]})
    assert created.status_code == 201
    wl_id = created.json()["id"]
    assert created.json()["tickers"] == ["MSFT", "NVDA"]  # cleaned + deduped

    assert len(client.get("/api/watchlists").json()["watchlists"]) == 1
    updated = client.put(f"/api/watchlists/{wl_id}",
                         json={"name": "AI", "tickers": ["MSFT"]})
    assert updated.json()["tickers"] == ["MSFT"]
    assert client.delete(f"/api/watchlists/{wl_id}").status_code == 204
    assert client.get(f"/api/watchlists/{wl_id}").status_code == 404


def test_chart_history(client):
    body = client.get("/api/charts/history", params={"ticker": "MSFT"}).json()
    assert body["symbol"] == "MSFT"
    assert len(body["closes"]) == 260
    assert client.get("/api/charts/history",
                      params={"ticker": "MSFT", "range": "bogus"}).status_code == 400
    assert client.get("/api/charts/history",
                      params={"ticker": "NOPE"}).status_code == 404


def test_news_endpoint(client):
    body = client.get("/api/news", params={"tickers": "MSFT"}).json()
    assert body["items"][0]["headline"] == "MSFT beats earnings"
    assert body["sentiment_by_ticker"]["MSFT"]["bullish"] == 1
    assert client.get("/api/news", params={"tickers": " "}).status_code == 400


def test_search(client):
    body = client.get("/api/search", params={"q": "micro"}).json()
    assert body["results"][0]["symbol"] == "MSFT"
