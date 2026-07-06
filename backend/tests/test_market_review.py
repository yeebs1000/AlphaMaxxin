"""Trading calendar + market review breadth — pure/offline."""
from datetime import datetime, timezone

from app import market_calendar as cal
from app.skills.market_review import compute_market_review, _breadth
from .fakes import FakeYahoo


def test_calendar_weekend_closed_everywhere():
    sat = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)  # Saturday
    for m in ("US", "SG", "HK", "JP", "KR"):
        s = cal.status(m, now=sat)
        assert s["is_open"] is False
        assert s["last_trading_day"] == "2026-07-03"  # Friday


def test_calendar_ticker_routing_and_session():
    assert cal.market_of_ticker("9988.HK") == "HK"
    assert cal.market_of_ticker("D05.SI") == "SG"
    assert cal.market_of_ticker("AAPL") == "US"
    wed_open = datetime(2026, 7, 8, 18, 0, tzinfo=timezone.utc)   # 14:00 NY
    wed_pre = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)    # 08:00 NY
    assert cal.status_of_ticker("AAPL", now=wed_open)["is_open"] is True
    assert cal.status_of_ticker("AAPL", now=wed_pre)["is_open"] is False


def test_breadth_counts_advancers_decliners():
    yahoo = FakeYahoo(quotes={
        "A": {"price": 1, "change_pct": 2.0}, "B": {"price": 1, "change_pct": -1.0},
        "C": {"price": 1, "change_pct": 0.0}})  # D absent → not counted
    b = _breadth(yahoo, ["A", "B", "C", "D"])
    assert b["advancers"] == 1 and b["decliners"] == 1 and b["unchanged"] == 1
    assert b["universe_size"] == 3
    assert b["advance_decline_ratio"] == 1.0
    assert b["avg_change_pct"] == round((2.0 - 1.0 + 0.0) / 3, 2)


def test_market_review_shape():
    yahoo = FakeYahoo(quotes={"^GSPC": {"price": 5800.0, "change_pct": 0.6}})
    review = compute_market_review(yahoo, regions=["US"])
    us = review["US"]
    assert us["index_symbol"] == "^GSPC"
    assert us["index_change_pct"] == 0.6
    assert us["market_status"]["market"] == "US"
    assert "advancers" in us["breadth"]
