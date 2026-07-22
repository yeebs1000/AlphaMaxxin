"""Stooq fallback: symbol mapping, CSV parse, live_ohlcv routing."""
from app.data import stooq
from app.data.live_quote import live_ohlcv
from tests.fakes import FakeYahoo

_CSV = """Date,Open,High,Low,Close,Volume
2026-07-18,100.0,102.0,99.0,101.5,1200000
2026-07-19,101.5,103.0,101.0,102.8,900000
2026-07-20,102.8,104.0,102.0,103.1,1100000
"""


def test_symbol_mapping_us_only():
    assert stooq.symbol_for("AAPL") == "aapl.us"
    assert stooq.symbol_for("brk-b") == "brk-b.us"
    assert stooq.symbol_for("9988.HK") is None      # suffixed → not ours
    assert stooq.symbol_for("D05.SI") is None
    assert stooq.symbol_for("0700") is None          # bare numeric HK code
    assert stooq.symbol_for("") is None


def test_parse_csv_shape_and_garbage():
    bars = stooq.parse_csv(_CSV)
    assert bars["closes"] == [101.5, 102.8, 103.1]
    assert bars["timestamps"][0] == "2026-07-18"
    assert bars["volumes"][1] == 900000
    assert stooq.parse_csv("<html>No data</html>") is None
    assert stooq.parse_csv("") is None
    # max_bars trims from the head, keeping the newest rows.
    assert stooq.parse_csv(_CSV, max_bars=2)["closes"] == [102.8, 103.1]


def test_live_ohlcv_falls_back_to_stooq(monkeypatch):
    monkeypatch.setattr(stooq, "ohlcv",
                        lambda t, interval="1d", max_bars=260: {"closes": [1.0]})
    # Yahoo has nothing, akshare not installed → stooq leg answers for US.
    bars = live_ohlcv("AAPL", FakeYahoo(), "1d", "1y")
    assert bars == {"closes": [1.0]}
