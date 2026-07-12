"""Tranche B: equity history metrics, dividend income view, min-variance tilt."""
import datetime

import numpy as np
import pytest

from app import equity_history
from app.skills import dividends, portfolio_construction as pc
from .fakes import FakeYFinance

D = datetime.date


# ---- equity history -----------------------------------------------------------

def _snap(value, cost=1000.0, count=3):
    return {"total_value_usd": value, "total_cost_usd": cost, "holdings_count": count}


def test_record_upserts_per_day(tmp_path):
    path = str(tmp_path / "eq.json")
    equity_history.record(_snap(1000), file_path=path, today=D(2026, 7, 1))
    equity_history.record(_snap(1010), file_path=path, today=D(2026, 7, 1))  # same day
    equity_history.record(_snap(1020), file_path=path, today=D(2026, 7, 2))
    rows = equity_history._load(path)
    assert [r["value_usd"] for r in rows] == [1010.0, 1020.0]  # last-write-wins
    equity_history.record({"total_value_usd": 0}, file_path=path)  # ignored
    assert len(equity_history._load(path)) == 2


def test_metrics_needs_history_and_adjusts_deposits(tmp_path):
    path = str(tmp_path / "eq.json")
    for i, (v, c) in enumerate([(1000, 1000), (1010, 1000), (1020, 1000),
                                (1530, 1500), (1540, 1500), (1550, 1500)]):
        equity_history.record(_snap(v, c), file_path=path, today=D(2026, 7, 1 + i))
    m = equity_history.metrics(path)
    # Day 4 added a $500 deposit; adjusted return that day is (1530-1010-500...
    # wait: (1530 - 1020 - 500)/1020 ≈ -1% — the deposit itself isn't return.
    assert m["n_snapshots"] == 6
    assert m["twr_pct"] < 5  # raw value grew 55%, but TWR strips the deposit
    assert m["max_drawdown_pct"] <= 0
    # Too little history → None.
    short = str(tmp_path / "short.json")
    equity_history.record(_snap(1000), file_path=short, today=D(2026, 7, 1))
    assert equity_history.metrics(short) is None


# ---- dividends ----------------------------------------------------------------

def test_income_view_yields_and_soon_flag():
    holdings = [{"ticker": "DIV", "cost_price": 50.0, "quantity": 10, "currency": "USD"},
                {"ticker": "NOPAY", "cost_price": 10.0, "quantity": 5, "currency": "USD"}]
    yf = FakeYFinance(dividends={"DIV": {"ttm_dps": 4.0, "ex_dividend_date": "2026-07-20"}})
    out = dividends.income_view(holdings, {}, {"DIV": {"price": 100.0}}, yf,
                                today=D(2026, 7, 10))
    d = out["by_ticker"]["DIV"]
    assert d["current_yield_pct"] == pytest.approx(4.0)   # 4/100
    assert d["yield_on_cost_pct"] == pytest.approx(8.0)   # 4/50
    assert d["ex_date_soon"] is True
    assert out["ex_dates_soon"][0]["in_days"] == 10
    assert "NOPAY" not in out["by_ticker"]
    assert dividends.income_view(holdings, {}, {}, FakeYFinance(available=False))["feed_ok"] is False


# ---- min-variance tilt --------------------------------------------------------

def test_min_variance_prefers_low_vol_and_respects_cap():
    rng = np.random.default_rng(5)
    n = 200
    returns = {"CALM": (rng.normal(0, 0.005, n)).tolist(),
               "WILD": (rng.normal(0, 0.03, n)).tolist(),
               "MID": (rng.normal(0, 0.012, n)).tolist(),
               "MID2": (rng.normal(0, 0.012, n)).tolist(),
               "MID3": (rng.normal(0, 0.012, n)).tolist(),
               "MID4": (rng.normal(0, 0.012, n)).tolist()}
    weights = {t: 1 / 6 for t in returns}
    out = pc.min_variance_tilt(weights, returns, cap=0.30)
    sw = out["suggested_weights"]
    assert sum(sw.values()) == pytest.approx(1.0, abs=0.01)
    assert sw["CALM"] > sw["WILD"]          # low-vol name gets more weight
    assert max(sw.values()) <= 0.30 + 1e-6  # cap respected
    assert out["covered"] == 6


def test_min_variance_degrades():
    assert pc.min_variance_tilt({"A": 1.0}, {"A": [0.01] * 100}) is None  # <3 names
    assert pc.min_variance_tilt({}, {}) is None