"""Money-weighted return (XIRR) — known-answer tests. Pure/offline."""
import datetime

from app.skills import money_weighted as mw

D = datetime.date


def test_exact_doubling_over_one_year_is_100pct():
    flows = [(D(2025, 1, 1), -1000.0), (D(2026, 1, 1), 2000.0)]
    assert abs(mw.xirr(flows) - 1.0) < 1e-4


def test_flat_return_is_zero():
    flows = [(D(2025, 1, 1), -1000.0), (D(2026, 1, 1), 1000.0)]
    assert abs(mw.xirr(flows)) < 1e-4


def test_ten_percent_over_one_year():
    flows = [(D(2025, 1, 1), -1000.0), (D(2026, 1, 1), 1100.0)]
    assert abs(mw.xirr(flows) - 0.10) < 1e-4


def test_annualises_a_short_holding_period():
    """+5% in ~3 months annualises to well above 20%, not 5%."""
    flows = [(D(2026, 1, 1), -1000.0), (D(2026, 4, 1), 1050.0)]
    rate = mw.xirr(flows)
    assert 0.20 < rate < 0.24          # (1.05)^(365/90) - 1 ~= 21.6%


def test_loss_is_negative():
    flows = [(D(2025, 1, 1), -1000.0), (D(2026, 1, 1), 800.0)]
    assert -0.21 < mw.xirr(flows) < -0.19


def test_timing_of_deposits_changes_mwr_but_not_the_raw_gain():
    """The whole point of MWR: same start, same end value, same total
    contributed — but money that arrived later earns for less time, so the
    money-weighted return is HIGHER on the same dollar gain."""
    early = [(D(2025, 1, 1), -1000.0), (D(2025, 2, 1), -1000.0),
             (D(2026, 1, 1), 2200.0)]
    late = [(D(2025, 1, 1), -1000.0), (D(2025, 11, 1), -1000.0),
            (D(2026, 1, 1), 2200.0)]
    assert mw.xirr(late) > mw.xirr(early)


def test_refuses_when_no_sign_change():
    """All money in and never out — no return is defined."""
    assert mw.xirr([(D(2025, 1, 1), -100.0), (D(2026, 1, 1), -100.0)]) is None


def test_refuses_degenerate_input():
    assert mw.xirr([]) is None
    assert mw.xirr([(D(2025, 1, 1), -100.0)]) is None            # single flow
    assert mw.xirr([(D(2025, 1, 1), -100.0),
                    (D(2025, 1, 1), 110.0)]) is None             # zero elapsed


def test_money_weighted_return_wrapper_uses_human_sign_convention():
    """Deposits are written POSITIVE (money added), flipped internally."""
    out = mw.money_weighted_return(
        deposits=[(D(2025, 1, 1), 1000.0)],
        current_value=1100.0, as_of=D(2026, 1, 1))
    assert abs(out["mwr_annual_pct"] - 10.0) < 0.05
    assert out["net_invested"] == 1000.0
    assert out["simple_gain_pct"] == 10.0
    assert out["days"] == 365 and out["n_flows"] == 1


def test_wrapper_handles_withdrawals():
    out = mw.money_weighted_return(
        deposits=[(D(2025, 1, 1), 1000.0), (D(2025, 7, 1), -200.0)],
        current_value=900.0, as_of=D(2026, 1, 1))
    assert out["net_invested"] == 800.0
    assert out["mwr_annual_pct"] is not None


def test_flows_from_snapshots_counts_the_opening_balance():
    """The series starts mid-life: the book already at work on day one is
    invested capital. Omitting it makes MWR the return on later top-ups only —
    a $3.5k deposit against a $15.9k book reads as an absurd gain."""
    rows = [
        {"date": "2026-07-01", "value_usd": 10000, "cost_usd": 10000},
        {"date": "2026-07-03", "value_usd": 15000, "cost_usd": 15000},  # +$5k
    ]
    flows = mw.flows_from_snapshots(rows)
    assert flows[0] == (D(2026, 7, 1), 10000.0)      # opening balance counted
    assert abs(flows[1][1] - 5000) < 1


def test_flows_from_snapshots_ignores_rounding_noise():
    """Cost-basis wobble of a few dollars is FX/rounding, not a deposit."""
    rows = [
        {"date": "2026-07-01", "value_usd": 10000, "cost_usd": 10000},
        {"date": "2026-07-02", "value_usd": 10010, "cost_usd": 10003},  # +$3 noise
        {"date": "2026-07-03", "value_usd": 15000, "cost_usd": 15000},  # +$5k real
    ]
    flows = mw.flows_from_snapshots(rows)
    assert len(flows) == 2                            # opening + the real one
    assert flows[1][0] == D(2026, 7, 3)
    assert abs(flows[1][1] - 4997) < 1


def test_flows_from_snapshots_empty():
    assert mw.flows_from_snapshots([]) == []
    assert mw.flows_from_snapshots(None) == []
