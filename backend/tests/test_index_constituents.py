"""Index constituents: table-column-finder, ticker normalization, and the
offline tripwire propagation — all pure/offline, no network."""
import pytest

from app.data.base import OfflineError
from app.data import index_constituents as idx


class _FakeTable:
    """Minimal stand-in for a pandas DataFrame slice this module needs:
    .columns and __getitem__ returning something with .tolist()."""
    def __init__(self, columns, rows):
        self.columns = columns
        self._rows = rows

    def __getitem__(self, col):
        i = self.columns.index(col)
        return _Col([r[i] for r in self._rows])


class _Col:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return self._values


def test_find_ticker_column_matches_header_hint():
    tables = [
        _FakeTable(["Company", "Sector"], [("Acme", "Tech")]),
        _FakeTable(["Symbol", "Security"], [("AAPL", "Apple"), ("BRK.B", "Berkshire")]),
    ]
    col = idx._find_ticker_column(tables, "symbol", "ticker")
    assert col == ["AAPL", "BRK.B"]


def test_find_ticker_column_no_match_returns_none():
    tables = [_FakeTable(["Company"], [("Acme",)])]
    assert idx._find_ticker_column(tables, "symbol", "ticker") is None


def test_sp500_normalizes_share_class_dots(monkeypatch):
    monkeypatch.setattr(idx, "_wiki_tables",
                        lambda page: [_FakeTable(["Symbol"], [("AAPL",), ("BRK.B",)])])
    monkeypatch.setattr(idx, "_cached", lambda key, fetch: fetch())
    assert idx.sp500_tickers() == ["AAPL", "BRK-B"]


def test_hang_seng_zero_pads_and_suffixes(monkeypatch):
    monkeypatch.setattr(idx, "_wiki_tables",
                        lambda page: [_FakeTable(["Stock Code"], [("700",), ("5",)])])
    monkeypatch.setattr(idx, "_cached", lambda key, fetch: fetch())
    assert idx.hang_seng_tickers() == ["0700.HK", "0005.HK"]


def test_sti_suffixes_si(monkeypatch):
    monkeypatch.setattr(idx, "_wiki_tables",
                        lambda page: [_FakeTable(["SGX Code"], [("D05",), ("O39",)])])
    monkeypatch.setattr(idx, "_cached", lambda key, fetch: fetch())
    assert idx.sti_tickers() == ["D05.SI", "O39.SI"]


def test_merge_dedupes_and_none_on_all_empty():
    assert idx._merge(["A", "B"], ["B", "C"]) == ["A", "B", "C"]
    assert idx._merge(None, None) is None
    assert idx._merge([], None) is None


def test_wiki_tables_offline_raises():
    # guard_online() sits OUTSIDE _wiki_tables' try/except on purpose — the
    # tripwire must propagate, not get silently swallowed as "no data".
    with pytest.raises(OfflineError):
        idx._wiki_tables("List_of_S%26P_500_companies")


def test_audit_against_ibkr_unavailable_returns_none(monkeypatch):
    import app.brokers.ibkr_client as ibkr
    monkeypatch.setattr(ibkr, "qualify_symbols", lambda specs: None)
    assert idx.audit_against_ibkr(["AAPL"], "US") is None
    assert idx.audit_against_ibkr([], "US") is None
    assert idx.audit_against_ibkr(["AAPL"], "JP") is None  # no IBKR mapping


def test_audit_against_ibkr_splits_resolved_and_builds_correct_specs(monkeypatch):
    import app.brokers.ibkr_client as ibkr
    captured = {}

    def fake_qualify(specs):
        captured["specs"] = specs
        return {s["key"]: s["symbol"] != "9999" for s in specs}

    monkeypatch.setattr(ibkr, "qualify_symbols", fake_qualify)
    out = idx.audit_against_ibkr(["0700.HK", "9999.HK"], "HK")
    assert out == {"resolved": ["0700.HK"], "unresolved": ["9999.HK"]}
    specs = {s["key"]: s for s in captured["specs"]}
    assert specs["0700.HK"] == {"key": "0700.HK", "symbol": "700",
                                "exchange": "SEHK", "currency": "HKD"}


def test_audit_against_ibkr_us_and_sg_symbol_conversion(monkeypatch):
    import app.brokers.ibkr_client as ibkr
    captured = {}

    def fake_qualify(specs):
        captured["specs"] = specs
        return {}

    monkeypatch.setattr(ibkr, "qualify_symbols", fake_qualify)
    idx.audit_against_ibkr(["BRK-B"], "US")
    assert captured["specs"][0]["symbol"] == "BRK B"
    assert captured["specs"][0]["exchange"] == "SMART"
    idx.audit_against_ibkr(["D05.SI"], "SG")
    assert captured["specs"][0] == {"key": "D05.SI", "symbol": "D05",
                                    "exchange": "SGX", "currency": "SGD"}


def test_universe_fns_propagate_offline_tripwire(tmp_path):
    # index_constituents itself doesn't catch OfflineError (same contract as
    # every other provider, e.g. YahooProvider.ohlcv) — screener.candidates_for
    # is the layer that catches it and falls back to the curated list.
    from app.data.base import DiskTTLCache
    idx._cache = DiskTTLCache(root=str(tmp_path))
    with pytest.raises(OfflineError):
        idx.us_universe()
    with pytest.raises(OfflineError):
        idx.hk_universe()
    with pytest.raises(OfflineError):
        idx.sg_universe()
