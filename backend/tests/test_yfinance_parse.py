"""yfinance statement parse — shape-contract test with REAL pandas frames.
The offline tripwire hides the network method from CI; this exercises the pure
parser directly so a column-shape drift (e.g. a string 'TTM' column) fails a
test instead of crashing the report's fundamentals stage."""
import datetime

import pandas as pd

from app.data.yfinance_provider import parse_statements

_ROWS = {"income": {"Total Revenue": "revenue", "Net Income": "net_income"}}


def _frame(columns):
    return pd.DataFrame(
        {c: [100.0, 90.0] for c in columns},
        index=["Total Revenue", "Net Income"])


def test_parse_statements_dated_columns():
    cols = [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]
    rows = parse_statements({"income": _frame(cols)}, _ROWS)
    assert [r["period"] for r in rows] == ["2025-12-31", "2024-12-31"]
    # _frame gives every column [100, 90] over index [Total Revenue, Net Income].
    assert rows[0]["revenue"] == 100.0 and rows[0]["net_income"] == 90.0


def test_parse_statements_skips_string_ttm_column_without_crashing():
    # yfinance sometimes includes a 'TTM' string column — col.date() would
    # AttributeError. The guard must skip it, keep the dated columns.
    cols = [pd.Timestamp("2025-12-31"), "TTM"]
    rows = parse_statements({"income": _frame(cols)}, _ROWS)
    assert len(rows) == 1 and rows[0]["period"] == "2025-12-31"   # TTM dropped


def test_parse_statements_empty_and_missing():
    assert parse_statements({"income": None}, _ROWS) is None
    assert parse_statements({"income": pd.DataFrame()}, _ROWS) is None
    # A frame with only string columns -> nothing dated -> None (not a crash).
    assert parse_statements({"income": _frame(["TTM", "current"])}, _ROWS) is None
