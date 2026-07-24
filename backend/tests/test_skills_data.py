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


def test_fetch_and_merge_runs_tickers_concurrently():
    """A slow fetch for one ticker must not delay the others behind it in
    a serial queue — this was the root cause of the news tab taking minutes
    for a full portfolio."""
    import threading
    import time

    tickers = [f"T{i}" for i in range(6)]
    start_times = {}
    barrier = threading.Barrier(len(tickers), timeout=2)

    class SlowFinnhub:
        available = True

        def news(self, ticker, days=7):
            start_times[ticker] = time.monotonic()
            barrier.wait()  # every ticker's fetch must be in-flight at once
            return [art(ticker, f"{ticker} story", 100)]

    registry = make_registry(finnhub=SlowFinnhub(), alphavantage=FakeAlphaVantage())
    merged = news.fetch_and_merge(registry, tickers, max_per_ticker=5)
    assert len(merged) == len(tickers)
    assert max(start_times.values()) - min(start_times.values()) < 1.0


def test_fetch_and_merge_empty_tickers():
    assert news.fetch_and_merge(make_registry(), []) == []


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
    # 3 momentum leaders; the rising bars aren't oversold so no extra channel.
    assert len(out["SG"]) == 3


def test_screener_oversold_channel_surfaces_low_rsi_names(monkeypatch):
    # Two rising leaders + one faller. With max_per_market=2 the faller can't
    # be a momentum leader, but the oversold channel must surface it so the
    # gate's rsi_reversion setup (the measured edge) can ever fire. Control the
    # universe directly — candidates_for() would hit the disk-cached real list.
    monkeypatch.setattr(screener, "candidates_for",
                        lambda region: ["RBLX", "ETSY", "CROX"])
    yahoo = FakeYahoo(ohlcv_data={
        "RBLX": _bars(100, 150),   # rising -> leader, high RSI
        "ETSY": _bars(100, 130),   # rising -> leader
        "CROX": _bars(150, 100),   # falling -> oversold (low RSI), weak momentum
    })
    out = screener.screen(yahoo, regions=["US"], max_per_market=2)
    tickers = [s["ticker"] for s in out["US"]]
    assert "CROX" in tickers                          # surfaced via oversold channel
    crox = next(s for s in out["US"] if s["ticker"] == "CROX")
    assert crox["rsi14"] < 35 and "momentum_rank" not in crox  # not a leader
    assert out["US"][0]["momentum_rank"] == 1          # leaders still ranked


def test_candidates_for_falls_back_when_dynamic_universe_unavailable():
    # ALPHAMAXXIN_OFFLINE=1 (conftest) makes the dynamic fetch raise —
    # candidates_for must catch it and return the curated list, never crash.
    assert screener.candidates_for("US") == screener.US_CANDIDATES
    assert screener.candidates_for("HK") == screener.HK_CANDIDATES
    assert screener.candidates_for("SG") == screener.SG_CANDIDATES
    assert screener.candidates_for("JP") == screener.JP_CANDIDATES  # no dynamic source


def test_candidates_for_prefers_dynamic_universe_when_available(monkeypatch):
    from app.data import index_constituents as idx
    monkeypatch.setattr(idx, "us_universe", lambda: ["ZZZ", "YYY"])
    assert screener.candidates_for("US") == ["ZZZ", "YYY"]


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


def test_macro_expanded_fred_series_and_balance_sheet_pace():
    fred = FakeFred({
        "T10YIE": _fred_series("T10YIE", [2.3]),
        # 14 weekly WALCL prints: contracting by 100 over the last 13
        "WALCL": _fred_series("WALCL", [7000 - i * 10 for i in range(14)]),
        "PCEPI": _fred_series("PCEPI", [120 + i * 0.2 for i in range(13)]),
        "ICSA": _fred_series("ICSA", [220000]),
    })
    snap = macro.compute_macro(fred, FakeYahoo())
    assert snap["rates"]["breakeven_10y"] == pytest.approx(2.3)
    assert snap["labor"]["jobless_claims"] == 220000
    assert snap["inflation"]["pce_yoy"] is not None
    assert snap["fed_balance_sheet"]["change_13w"] == pytest.approx(-130)
    assert snap["regime_flags"]["fed_balance_sheet_contracting"] is True


def test_macro_regional_signals_from_real_momentum():
    def bars(start, end, n=63):
        closes = [start + (end - start) * i / (n - 1) for i in range(n)]
        return {"closes": closes, "highs": closes, "lows": closes, "volumes": [1] * n}

    yahoo = FakeYahoo(ohlcv_data={
        "^HSI": bars(100, 116),      # +16% over 3mo -> strong positive
        "CNY=X": bars(100, 101),     # +1% FX move
    })
    snap = macro.compute_macro(FakeFred(), yahoo, regions=["HK"])
    signal = snap["regional_signals"][0]
    assert signal["region"] == "HK"
    assert signal["index_momentum_3m_pct"] == pytest.approx(16.0)
    assert signal["composite_score"] > 0
    assert -2.0 <= signal["composite_score"] <= 2.0


def test_macro_regional_signal_none_without_data():
    snap = macro.compute_macro(FakeFred(), FakeYahoo(), regions=["JP"])
    signal = snap["regional_signals"][0]
    assert signal["index_momentum_3m_pct"] is None
    assert signal["composite_score"] is None


def test_macro_ppi_nfp_and_fed_dot_plot():
    fred = FakeFred({
        "DGS2": _fred_series("DGS2", [4.0]),
        "PPIFIS": _fred_series("PPIFIS", [100 + i * 0.3 for i in range(13)]),
        "PPICOR": _fred_series("PPICOR", [100 + i * 0.4 for i in range(13)]),
        # 2 monthly NFP prints: +150k over the latest month.
        "PAYEMS": _fred_series("PAYEMS", [158000, 158150]),
        "FEDTARMD": _fred_series("FEDTARMD", [3.9]),
        "FEDTARMDLR": _fred_series("FEDTARMDLR", [3.0]),
    })
    snap = macro.compute_macro(fred, FakeYahoo())
    assert snap["producer_prices"]["ppi_yoy"] is not None
    assert snap["producer_prices"]["core_ppi_yoy"] is not None
    assert snap["labor"]["nonfarm_payrolls_change_k"] == pytest.approx(150.0)
    assert snap["fed_dot_plot"]["median_next_year"] == pytest.approx(3.9)
    assert snap["fed_dot_plot"]["median_longer_run"] == pytest.approx(3.0)
    # market_vs_fed_gap = ust2y (4.0) - median_next_year (3.9) = +0.1
    assert snap["fed_dot_plot"]["market_vs_fed_gap"] == pytest.approx(0.1)
    assert snap["regime_flags"]["payrolls_cooling"] is False  # +150k >= 100k


def test_macro_ppi_nfp_dot_plot_missing_is_none():
    snap = macro.compute_macro(FakeFred(), FakeYahoo())
    assert snap["producer_prices"]["ppi_yoy"] is None
    assert snap["labor"]["nonfarm_payrolls_change_k"] is None
    assert snap["fed_dot_plot"]["median_next_year"] is None
    assert snap["fed_dot_plot"]["market_vs_fed_gap"] is None
    assert snap["regime_flags"]["producer_inflation_hot"] is False
    assert snap["regime_flags"]["payrolls_cooling"] is False


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


def _year(period, *, ni=100, ta=1000, cfo=140, debt=200, ca=300, cl=150,
          shares=50, rev=800, cogs=400):
    return {"period": period, "net_income": ni, "total_assets": ta, "cfo": cfo,
            "total_debt": debt, "current_assets": ca, "current_liabilities": cl,
            "shares": shares, "revenue": rev, "cogs": cogs}


def test_f_score_all_nine_pass():
    # y0 improves on every axis vs y1 → 9/9.
    y1 = _year("2024-12-31", ni=50, ta=1000, cfo=40, debt=300, ca=250,
               cl=150, shares=52, rev=700, cogs=400)
    y0 = _year("2025-12-31")
    fs = fundamentals.f_score([y0, y1])
    assert fs["score"] == 9 and fs["known"] == 9
    assert fs["period"] == "2025-12-31"


def test_f_score_missing_inputs_drop_from_known():
    # A bank-shaped row: no COGS, no current ratio → those criteria unknown.
    y0 = {"period": "2025-12-31", "net_income": 100, "total_assets": 1000,
          "cfo": 140, "total_debt": 200, "revenue": 800, "shares": 50}
    y1 = {"period": "2024-12-31", "net_income": 50, "total_assets": 1000,
          "cfo": 40, "total_debt": 300, "revenue": 700, "shares": 52}
    fs = fundamentals.f_score([y0, y1])
    assert fs["known"] == 7                       # margin_up + liquidity_up unknown
    assert fs["criteria"]["margin_up"] is None
    assert fs["criteria"]["liquidity_up"] is None
    assert fs["score"] == 7


def test_f_score_penalizes_deterioration_and_needs_two_years():
    y1 = _year("2024-12-31")
    y0 = _year("2025-12-31", ni=-20, cfo=-30, debt=500, shares=60,
               rev=600, cogs=400)
    fs = fundamentals.f_score([y0, y1])
    assert fs["score"] <= 2                       # nearly everything worsened
    assert fundamentals.f_score([y0]) is None
    assert fundamentals.f_score(None) is None


def test_fundamentals_short_interest_and_flag():
    raw = {"ticker": "SHRT", "price": 10.0, "short_ratio": 6.2,
           "short_pct_float": 0.23, "shares_short": 4.5e7}
    snap = fundamentals.compute_fundamentals("SHRT", raw)
    si = snap["short_interest"]
    assert si["ratio_days"] == 6.2 and si["pct_float"] == 0.23
    assert any("heavily shorted (23% of float)" in f for f in snap["quality_flags"])
    # Below threshold → no flag.
    ok = fundamentals.compute_fundamentals("OK", {"ticker": "OK", "price": 1.0,
                                                  "short_pct_float": 0.03})
    assert not any("shorted" in f for f in ok["quality_flags"])


def test_fundamentals_analyst_trend_from_rec_trends():
    trends = [{"period": "2026-07-01", "strongBuy": 13, "buy": 23, "hold": 16,
               "sell": 2, "strongSell": 0},
              {"period": "2026-06-01", "strongBuy": 14, "buy": 24, "hold": 15,
               "sell": 2, "strongSell": 0},
              {"period": "2026-05-01", "strongBuy": 12, "buy": 20, "hold": 18,
               "sell": 3, "strongSell": 1},
              {"period": "2026-04-01", "strongBuy": 10, "buy": 18, "hold": 20,
               "sell": 5, "strongSell": 2}]
    snap = fundamentals.compute_fundamentals("AAA", {"ticker": "AAA", "price": 1.0},
                                             rec_trends=trends)
    t = snap["analyst"]["trend"]
    assert t["net_buy"] == 34            # 13+23-2-0
    assert t["net_buy_3m_ago"] == 21     # 10+18-5-2
    assert t["delta_3m"] == 13           # upgrading
    # Short history → no delta, no crash.
    short = fundamentals.compute_fundamentals("BBB", {"ticker": "BBB", "price": 1.0},
                                              rec_trends=trends[:1])
    assert short["analyst"]["trend"]["delta_3m"] is None


def test_fundamentals_finnhub_drops_non_numeric_sentinel():
    """Finnhub's free tier occasionally emits a sentinel string ("NM") for
    an undefined ratio instead of omitting the field — must be dropped, not
    passed into a numeric comparison in _quality_flags."""
    metrics = {"metric": {"peTTM": "NM", "debtToEquity": "N/A",
                          "revenueGrowthTTMYoy": 12.0}}
    snap = fundamentals.compute_fundamentals("DDD", None, metrics)
    assert snap["valuation"]["pe_ttm"] is None
    assert snap["balance"]["debt_to_equity"] is None
    assert snap["quality_flags"] == []  # never raises comparing None


def test_yfinance_sanitize_info_drops_infinity_string():
    """yfinance's real-world failure mode: an undefined ratio (e.g. P/E
    with negative trailing earnings) serialized as the string "Infinity"
    instead of a numeric type — this crashed _quality_flags's `pe > 60`."""
    from app.data.yfinance_provider import sanitize_info
    info = {"trailingPE": "Infinity", "forwardPE": 25.0, "currentPrice": 50.0,
            "sector": "Technology"}
    raw = sanitize_info("AAA", info)
    assert "pe_ttm" not in raw          # non-numeric dropped
    assert raw["fwd_pe"] == 25.0        # numeric fields still pass through
    assert raw["sector"] == "Technology"  # string fields unaffected
    snap = fundamentals.compute_fundamentals("AAA", raw)
    assert snap["valuation"]["pe_ttm"] is None
    assert snap["quality_flags"] == []  # would have raised before the fix


def test_snapshot_builder_coerces_poisoned_raw_dict():
    """Backstop: even if a poisoned raw dict reaches compute_fundamentals
    directly (a stale disk-cache entry written before the provider fix
    shipped — exactly what kept crashing this in the wild), the snapshot
    builder coerces every numeric field, so no downstream consumer sees a
    string where it expects a number."""
    from app.skills import signals
    # This is the real shape of the poisoned A31.SI cache entry that crashed.
    poisoned = {"ticker": "A31.SI", "pe_ttm": "Infinity", "fwd_pe": 27.66,
                "net_margin": 0.19, "rev_yoy": 0.63, "debt_to_equity": 0.51,
                "target_mean": 0.34, "price": 0.143, "sector": "Technology"}
    snap = fundamentals.compute_fundamentals("A31.SI", poisoned)  # must not raise
    assert snap["valuation"]["pe_ttm"] is None       # "Infinity" coerced to None
    assert snap["valuation"]["fwd_pe"] == 27.66
    assert isinstance(snap["quality_flags"], list)
    # The composite aggregator is the second consumer that compared these
    # numerically — it must also survive the poisoned snapshot.
    assert signals.fundamental_score(snap) is not None


def test_fundamental_score_survives_string_fields():
    """fundamental_score compared growth/margin/target fields numerically —
    guard it directly against a snapshot whose numerics are strings."""
    from app.skills import signals
    snap = {"quality_flags": [], "growth": {"rev_yoy": "NaN"},
            "margins": {"net": "N/A"}, "analyst": {"target_mean": "Infinity"},
            "price": "50"}
    assert signals.fundamental_score(snap) == 0  # no flags, all comparisons no-op


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
