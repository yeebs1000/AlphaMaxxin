"""live_quote/live_ohlcv: moomoo preferred when connected, Yahoo fallback
otherwise — this is the fix for HK/CN tickers (e.g. Xiaomi "01810") that
Yahoo can't resolve on its own, and for portfolio totals silently dropping
holdings whose quote fetch failed."""
from app.data.live_quote import live_quote, live_ohlcv
from app.data.yahoo import YahooProvider
from .fakes import FakeYahoo


def test_live_quote_prefers_moomoo_when_available(monkeypatch):
    from app.brokers import moomoo_client
    monkeypatch.setattr(moomoo_client, "MOOMOO_AVAILABLE", True)
    monkeypatch.setattr(moomoo_client, "get_moomoo_quote",
                        lambda t: {"price": 42.0, "currency": "HKD", "ticker": t})
    yahoo = FakeYahoo(quotes={"1810.HK": {"price": 999.0}})  # would be wrong if used
    result = live_quote("01810", yahoo)
    assert result == {"price": 42.0, "currency": "HKD", "ticker": "01810"}


def test_live_quote_falls_back_to_yahoo_when_moomoo_has_no_data(monkeypatch):
    from app.brokers import moomoo_client
    monkeypatch.setattr(moomoo_client, "MOOMOO_AVAILABLE", True)
    monkeypatch.setattr(moomoo_client, "get_moomoo_quote", lambda t: None)
    yahoo = FakeYahoo(quotes={"MSFT": {"price": 400.0}},
                      search_results={"MSFT": [{"symbol": "MSFT", "name": "Microsoft",
                                                "type": "EQUITY"}]})
    assert live_quote("MSFT", yahoo)["price"] == 400.0


def test_live_quote_falls_back_when_moomoo_unavailable(monkeypatch):
    from app.brokers import moomoo_client
    monkeypatch.setattr(moomoo_client, "MOOMOO_AVAILABLE", False)
    yahoo = FakeYahoo(quotes={"MSFT": {"price": 400.0}})
    assert live_quote("MSFT", yahoo)["price"] == 400.0


def test_live_ohlcv_prefers_moomoo_kline(monkeypatch):
    from app.brokers import moomoo_client
    monkeypatch.setattr(moomoo_client, "MOOMOO_AVAILABLE", True)
    rows = [{"open": 9.5, "close": 10.0, "high": 11.0, "low": 9.0, "volume": 100.0},
            {"open": 10.5, "close": 12.0, "high": 13.0, "low": 11.0, "volume": 200.0}]
    monkeypatch.setattr(moomoo_client, "get_moomoo_kline", lambda t, ktype: rows)
    yahoo = FakeYahoo(ohlcv_data={"1810.HK": {"closes": [1], "highs": [1],
                                              "lows": [1], "volumes": [1]}})
    bars = live_ohlcv("01810", yahoo, "1d", "1y")
    assert bars == {"opens": [9.5, 10.5], "closes": [10.0, 12.0],
                    "highs": [11.0, 13.0], "lows": [9.0, 11.0],
                    "volumes": [100.0, 200.0]}


def test_live_ohlcv_falls_back_to_yahoo(monkeypatch):
    from app.brokers import moomoo_client
    monkeypatch.setattr(moomoo_client, "MOOMOO_AVAILABLE", True)
    monkeypatch.setattr(moomoo_client, "get_moomoo_kline", lambda t, ktype: None)
    yahoo = FakeYahoo(ohlcv_data={"1810.HK": {"closes": [5], "highs": [5],
                                              "lows": [5], "volumes": [5]}})
    assert live_ohlcv("01810", yahoo, "1d", "1y")["closes"] == [5]


def test_yahoo_resolve_symbol_numeric_hk_fallback():
    yahoo = YahooProvider(cache=None)
    assert yahoo.resolve_symbol("01810") == ("1810.HK", "01810")
    assert yahoo.resolve_symbol("9988") == ("9988.HK", "9988")
