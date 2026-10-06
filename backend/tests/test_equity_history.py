"""Snapshot integrity and initial drawdown, with no provider calls."""
import datetime

import pytest

from app import equity_history
from app.skills.performance import portfolio_summary


def test_incomplete_snapshot_does_not_invent_performance(tmp_path):
    path = str(tmp_path / "equity.json")
    holdings = [{"ticker": ticker, "quantity": 1, "cost_price": 50,
                 "currency": "USD"} for ticker in ("A", "B")]
    quotes = {ticker: {"price": 100, "currency": "USD"} for ticker in ("A", "B")}
    for day in range(7):
        summary = portfolio_summary(holdings, {"A": quotes["A"]} if day == 3 else quotes)
        recorded = equity_history.record(
            summary, file_path=path,
            today=datetime.date(2026, 10, 1) + datetime.timedelta(days=day))
        assert recorded is (day != 3)
    assert len(equity_history._load(path)) == 6
    assert equity_history.metrics(path)["twr_pct"] == 0.0


def test_rejected_snapshot_preserves_existing_history(tmp_path):
    path = tmp_path / "equity.json"
    old = b'[{"date":"2026-10-01","value_usd":200,"cost_usd":100}]'
    path.write_bytes(old)
    assert equity_history.record({"total_value_usd": 100, "total_cost_usd": 50,
                                   "errors": ["no price for B"]}, file_path=str(path)) is False
    assert path.read_bytes() == old


@pytest.mark.parametrize("value, cost", [(float("nan"), 50), (100, None), (100, float("inf"))])
def test_nonfinite_or_incomplete_values_are_not_recorded(tmp_path, value, cost):
    path = tmp_path / "equity.json"
    assert equity_history.record({"total_value_usd": value, "total_cost_usd": cost},
                                  file_path=str(path)) is False
    assert not path.exists()


def test_first_interval_loss_counts_in_max_drawdown(tmp_path):
    path = str(tmp_path / "equity.json")
    for day, value in enumerate([200, 100, 100, 100, 100]):
        equity_history.record({"total_value_usd": value, "total_cost_usd": 100},
                              file_path=path, today=datetime.date(2026, 10, day + 1))
    metrics = equity_history.metrics(path)
    assert metrics["twr_pct"] == -50.0
    assert metrics["max_drawdown_pct"] == -50.0


@pytest.mark.parametrize("original", [
    b"[{broken JSON", b"{}", b'[{"date":"2026-10-01","value_usd":200}]',
    b'[{"date":"invalid","value_usd":200,"cost_usd":100}]',
    b'[{"date":"2026-10-01","value_usd":0,"cost_usd":100}]',
])
def test_corrupt_existing_history_is_never_replaced_by_a_new_snapshot(tmp_path, original):
    path = tmp_path / "equity.json"
    path.write_bytes(original)
    assert equity_history.record({"total_value_usd": 200, "total_cost_usd": 100},
                                 file_path=str(path)) is False
    assert path.read_bytes() == original
