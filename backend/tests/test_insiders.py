"""Insider Form-4 digest: code filtering, windowing, cluster detection."""
import datetime

from app.skills import insiders

TODAY = datetime.date(2026, 7, 1)


def _row(name, code, change, tdate):
    return {"name": name, "transactionCode": code, "change": change,
            "transactionDate": tdate, "share": 1000, "transactionPrice": 10.0}


def test_digest_filters_codes_and_window():
    rows = [
        _row("BUYER A", "P", 5000, "2026-06-20"),
        _row("SELLER B", "S", -2000, "2026-06-01"),
        _row("GIFT C", "G", -65000, "2026-06-15"),      # gift → ignored
        _row("EXERCISE D", "M", 10000, "2026-06-10"),   # option exercise → ignored
        _row("OLD E", "P", 9999, "2026-01-01"),         # outside 90d window
        _row("BAD F", "P", 100, "not-a-date"),          # unparseable → skipped
    ]
    d = insiders.digest_transactions(rows, today=TODAY)
    assert d["open_market_buys"] == 1 and d["open_market_sells"] == 1
    assert d["distinct_buyers"] == 1 and d["cluster_buying"] is False
    assert d["net_shares"] == 3000
    assert d["latest_buy"] == "2026-06-20" and d["latest_sell"] == "2026-06-01"


def test_cluster_needs_three_distinct_buyers():
    rows = [_row("A", "P", 100, "2026-06-01"),
            _row("A", "P", 100, "2026-06-02"),   # same person twice ≠ cluster
            _row("B", "P", 100, "2026-06-03")]
    assert insiders.digest_transactions(rows, today=TODAY)["cluster_buying"] is False
    rows.append(_row("C", "P", 100, "2026-06-04"))
    assert insiders.digest_transactions(rows, today=TODAY)["cluster_buying"] is True


def test_fetch_insiders_marks_feed_and_skips_quiet_tickers():
    class FakeFinnhub:
        available = True
        def insider_transactions(self, t):
            return [_row("A", "P", 100, "2026-06-01")] if t == "ACT" else []
    out = insiders.fetch_insiders(FakeFinnhub(), ["ACT", "QUIET"], today=TODAY)
    assert out["feed_ok"] is True
    assert "ACT" in out["by_ticker"] and "QUIET" not in out["by_ticker"]

    class Down:
        available = False
    assert insiders.fetch_insiders(Down(), ["ACT"])["feed_ok"] is False
