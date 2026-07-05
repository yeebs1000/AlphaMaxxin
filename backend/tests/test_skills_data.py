"""News digest, screener, catalysts, macro, fundamentals, politician trades —
all against fixture data via the fake providers."""
import datetime

import pytest

from app.skills import news, screener, catalysts, macro, fundamentals, politician_trades
from .fakes import FakeYahoo, FakeFinnhub, FakeAlphaVantage, FakeFred, make_registry


def art(ticker, title, epoch, sentiment="neutral", score=0.0, url=None):
    return {"title": title, "url": url or f"https://x.test/{ticker}/{epoch}",
            "source": "Test", "published_epoch": epoch, "published_rel": "1h ago",
            "ticker": ticker, "summary": "", "sentiment": sentiment,
            "sentiment_score": score, "provider": "test"}


# ---------------------------------------------------------------------------
# news
# ---------------------------------------------------------------------------
def test_merge_dedupes_by_url_and_title():
    a1 = art("AAA", "Same headline about something", 100, url="https://x.test/1")
    a2 = art("BBB", "Same headline about something", 200, url="https://x.test/2")  # dup title
    a3 = art("BBB", "Different headline", 300, url="https://x.test/1")             # dup url
    merged = news.merge_articles({"AAA": [a1], "BBB": [a2, a3]})
    assert len(merged) == 1
    assert merged[0]["ticker"] == "AAA"


def test_merge_sorts_newest_first_and_caps():
    arts = [art("AAA", f"headline {i} is unique enough", i) for i in range(10)]
    merged = news.merge_articles({"AAA": arts}, max_per_ticker=3)
    assert len(merged) == 3
    epochs = [a["published_epoch"] for a in merged]
    assert epochs == sorted(epochs, reverse=True)


def test_fetch_and_merge_prefers_av_then_finnhub():
    registry = make_registry(
        alphavantage=FakeAlphaVantage({"AAA": [art("AAA", "av story one", 100, "bullish", 0.5)]}),
        finnhub=FakeFinnhub({"AAA": [art("AAA", "finnhub story two", 90)]}),
    )
    merged = news.fetch_and_merge(registry, ["AAA"], max_per_ticker=5)
    providers = {a["title"] for a in merged}
    assert providers == {"av story one", "finnhub story two"}


def test_digest_prioritizes_sentiment_and_aggregates():
    arts = [art("AAA", "neutral latest", 300),
            art("AAA", "bullish older", 100, "bullish", 0.6),
            art("AAA", "bearish mid", 200, "bearish", -0.4)]
    d = news.digest(arts, max_items=2)
    assert [i["headline"] for i in d["items"]] == ["bearish mid", "bullish older"]
    agg = d["sentiment_by_ticker"]["AAA"]
    assert agg["count"] == 3 and agg["bullish"] == 1 and agg["bearish"] == 1
    assert agg["avg_score"] == pytest.approx((0.6 - 0.4) / 3)


# ---------------------------------------------------------------------------
# screener
# ---------------------------------------------------------------------------
def _bars(start, end, n=260):
    closes = [start + (end - start) * i / (n - 1) for i in range(n)]
    return {"closes": closes, "highs": [c + 1 for c in closes],
            "lows": [c - 1 for c in closes], "volumes": [1000] * n}


def test_screener_excludes_us_runners_and_ranks():
    yahoo = FakeYahoo(ohlcv_data={
        "RBLX": _bars(100, 150),   # +50% YoY — kept
        "DKNG": _bars(100, 250),   # +150% — excluded (US rule)
        "ETSY": _bars(100, 110),   # +10% — kept
    })
    out = screener.screen(yahoo, regions=["US"], max_per_market=6)
    tickers = [s["ticker"] for s in out["US"]]
    assert "DKNG" not in tickers
    assert set(tickers) == {"RBLX", "ETSY"}
    assert out["US"][0]["momentum_rank"] == 1
    assert out["US"][0]["mom_3m_pct"] >= out["US"][1]["mom_3m_pct"]


def test_screener_caps_per_market():
    yahoo = FakeYahoo(ohlcv_data={t: _bars(100, 120) for t in screener.SG_CANDIDATES})
    out = screener.screen(yahoo, regions=["SG"], max_per_market=3)
    assert len(out["SG"]) == 3


# ---------------------------------------------------------------------------
# catalysts
# ---------------------------------------------------------------------------
def test_calendar_filters_earnings_to_tickers():
    fh = FakeFinnhub(
        earnings=[{"date": "2026-07-10", "symbol": "AAA", "epsEstimate": 1.5, "hour": "amc"},
                  {"date": "2026-07-12", "symbol": "ZZZ", "epsEstimate": 0.2}],
        ipos=[{"date": "2026-07-11", "name": "NewCo", "symbol": "NEW",
               "price": "18-20", "exchange": "NASDAQ"}])
    cal = catalysts.build_calendar(fh, ["AAA", "BBB"],
                                   today=datetime.date(2026, 7, 5))
    types = [(e["type"], e["ticker"]) for e in cal["events"]]
    assert ("earnings", "AAA") in types
    assert all(t[1] != "ZZZ" for t in types)          # not our ticker
    assert ("ipo", "NEW") in types                    # IPOs are market-wide
    assert cal["upcoming_earnings_count"] == 1
    assert cal["events"] == sorted(cal["events"], key=lambda e: e["date"])


def test_calendar_degrades_without_finnhub():
    cal = catalysts.build_calendar(FakeFinnhub(available=False), ["AAA"])
    assert cal == {"events": [], "upcoming_earnings_count": 0, "source_available": False}


# ---------------------------------------------------------------------------
# macro
# ---------------------------------------------------------------------------
def _fred_series(series_id, values):
    return {"series_id": series_id,
            "observations": [{"date": f"2026-{i+1:02d}-01", "value": v}
                             for i, v in enumerate(values)]}


def test_macro_snapshot_computes_curve_and_yoy():
    fred = FakeFred({
        "FEDFUNDS": _fred_series("FEDFUNDS", [4.5]),
        "DGS2": _fred_series("DGS2", [4.0]),
        "DGS10": _fred_series("DGS10", [3.5]),
        # 13 monthly CPI observations: 300 → 312 = +4.0% YoY
        "CPIAUCSL": _fred_series("CPIAUCSL", [300 + i for i in range(13)]),
    })
    yahoo = FakeYahoo(quotes={"^VIX": {"price": 30.0, "change_pct": 5.0},
                              "^GSPC": {"price": 5800.0, "change_pct": -1.0}})
    snap = macro.compute_macro(fred, yahoo)
    assert snap["rates"]["curve_2s10s"] == pytest.approx(-0.5)
    assert snap["regime_flags"]["curve_inverted"] is True
    assert snap["inflation"]["cpi_yoy"] == pytest.approx(4.0)
    assert snap["regime_flags"]["inflation_above_target"] is True
    assert snap["regime_flags"]["risk_off"] is True          # VIX 30
    assert snap["indices"]["spx"]["price"] == 5800.0
    assert snap["indices"]["hsi"] is None                    # no quote → None, never invented


def test_macro_handles_missing_fred():
    snap = macro.compute_macro(FakeFred(), FakeYahoo())
    assert snap["rates"]["fed_funds"] is None
    assert snap["regime_flags"]["curve_inverted"] is False


# ---------------------------------------------------------------------------
# fundamentals
# ---------------------------------------------------------------------------
def test_fundamentals_from_yfinance_with_flags():
    raw = {"ticker": "AAA", "name": "Alpha", "pe_ttm": 80.0, "rev_yoy": -0.05,
           "net_margin": -0.02, "debt_to_equity": 250.0, "fcf": -1e6,
           "price": 100.0, "target_mean": 120.0}
    snap = fundamentals.compute_fundamentals("AAA", raw)
    assert snap["source"] == "yfinance"
    assert snap["valuation"]["pe_ttm"] == 80.0
    flags = " | ".join(snap["quality_flags"])
    for expected in ("P/E", "levered", "unprofitable", "shrinking", "free cash flow"):
        assert expected in flags


def test_fundamentals_finnhub_fallback_normalizes_percentages():
    metrics = {"metric": {"peTTM": 22.0, "revenueGrowthTTMYoy": 12.0,
                          "netProfitMarginTTM": 18.0}}
    snap = fundamentals.compute_fundamentals("BBB", None, metrics)
    assert snap["source"] == "finnhub"
    assert snap["growth"]["rev_yoy"] == pytest.approx(0.12)
    assert snap["margins"]["net"] == pytest.approx(0.18)
    assert snap["quality_flags"] == []


def test_fundamentals_none_without_sources():
    assert fundamentals.compute_fundamentals("CCC", None, None) is None


# ---------------------------------------------------------------------------
# politician trades
# ---------------------------------------------------------------------------
def test_politician_trades_filter_window_and_tickers():
    transactions = {
        "senate": [
            {"ticker": "AAA", "senator": "Sen. X", "type": "Purchase",
             "amount": "$15,001 - $50,000", "transaction_date": "2026-06-20"},
            {"ticker": "AAA", "senator": "Sen. Old", "type": "Sale",
             "amount": "$1,001 - $15,000", "transaction_date": "2025-01-01"},  # stale
            {"ticker": "ZZZ", "senator": "Sen. Y", "type": "Purchase",
             "amount": "$1,001 - $15,000", "transaction_date": "2026-06-25"},  # wrong ticker
        ],
        "house": [
            {"ticker": "BBB", "representative": "Rep. Z", "type": "purchase",
             "amount": "$1,001 - $15,000", "transaction_date": "06/28/2026"},  # house date fmt
        ],
        "feed_ok": True,
    }
    out = politician_trades.recent_trades(transactions, ["AAA", "BBB"],
                                          window_days=90,
                                          today=datetime.date(2026, 7, 5))
    assert out["feed_ok"] is True
    assert [(t["ticker"], t["chamber"]) for t in out["trades"]] == \
        [("BBB", "house"), ("AAA", "senate")]  # newest first


def test_politician_trades_feed_down():
    out = politician_trades.recent_trades({"senate": [], "house": [], "feed_ok": False},
                                          ["AAA"])
    assert out == {"trades": [], "feed_ok": False}
