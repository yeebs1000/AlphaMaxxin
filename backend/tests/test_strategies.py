"""Strategy panel — deterministic verdicts, conflict counting, graceful skip."""
from app.skills import strategies as st


def _bull_snap():
    return {"sma50": 110, "sma200": 100, "rsi14": 25, "last_close": 120,
            "macd": {"histogram": 0.5}, "higher_timeframe_trend": "Uptrend",
            "bollinger": {"upper": 118, "lower": 95},
            "last_volume": 300, "avg_volume_20d": 100}


def test_all_strategies_fire_bullish():
    p = st.panel(["X"], {"X": _bull_snap()}, {"X": {"pe_ttm": 15, "rev_yoy": 0.2}})
    assert p["X"]["bull"] == 7 and p["X"]["bear"] == 0
    assert p["X"]["net_score"] > 0


def test_panel_records_conflict():
    # Death cross + overbought RSI + negative MACD, but price still > 200DMA.
    snap = {"sma50": 90, "sma200": 100, "rsi14": 75, "last_close": 105,
            "macd": {"histogram": -0.3}, "higher_timeframe_trend": "Flat",
            "bollinger": {"upper": 118, "lower": 95}}
    p = st.panel(["Y"], {"Y": snap})
    v = p["Y"]
    assert v["bear"] >= 2 and v["bull"] >= 1          # genuine disagreement captured
    assert isinstance(v["net_score"], float)


def test_ticker_without_data_is_absent():
    p = st.panel(["Z"], {"Z": {"last_close": 10}})   # nothing computable → no verdicts
    assert "Z" not in p


def test_rsi_reversion_only_fires_at_extremes():
    assert st.rsi_reversion({"technicals": {"rsi14": 50}}) is None
    assert st.rsi_reversion({"technicals": {"rsi14": 20}})["stance"] == "bullish"
