"""Index constituents: normalizers, the first-with-enough column picker, and
offline tripwire — all pure/offline (fake tables), no network. Formats mirror
the real Wikipedia pages validated live 2026-07-24."""
import pytest

from app.data.base import OfflineError
from app.data import index_constituents as idx


class _FakeTable:
    """Minimal stand-in for a pandas DataFrame slice _extract needs."""
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


# ---------------------------------------------------------------------------
# per-region cell normalizers
# ---------------------------------------------------------------------------
def test_us_code_normalizes_and_filters():
    assert idx._us_code("AAPL") == "AAPL"
    assert idx._us_code("BRK.B") == "BRK-B"         # share class dot -> dash
    assert idx._us_code("brk.b") == "BRK-B"
    assert idx._us_code("123") is None              # not a symbol
    assert idx._us_code("") is None


def test_hk_code_extracts_digits_from_sehk_format():
    assert idx._hk_code("SEHK:\xa0388") == "0388.HK"   # real Wikipedia format
    assert idx._hk_code("5") == "0005.HK"
    assert idx._hk_code("0700") == "0700.HK"
    assert idx._hk_code("HSBC") is None                 # no digits


def test_sg_code_strips_sgx_prefix():
    assert idx._sg_code("SGX: A17U") == "A17U.SI"       # real Wikipedia format
    assert idx._sg_code("D05") == "D05.SI"
    assert idx._sg_code("9CI") == "9CI.SI"
    assert idx._sg_code("") is None


# ---------------------------------------------------------------------------
# _extract — first hint-matching column with >= _MIN_VALID valid tickers
# ---------------------------------------------------------------------------
def test_extract_takes_first_real_constituents_column():
    syms = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III",
            "JJJ", "KKK", "LLL"]                       # alpha only (real S&P shape)
    tables = [_FakeTable(["Symbol"], [(s,) for s in syms])]
    out = idx._extract(tables, ("symbol",), idx._us_code)
    assert out == syms


def test_extract_skips_stray_small_column():
    # An early table matches the hint but normalizes to <10 valid -> skipped;
    # the real constituents table (>=10) wins. (The old first-match's HK bug.)
    stray = _FakeTable(["Code"], [("n/a",), ("SEHK: x",)])          # 0 valid HK codes
    real = _FakeTable(["Ticker"], [(f"SEHK:\xa0{i}",) for i in range(1, 15)])
    out = idx._extract([stray, real], ("ticker", "code"), idx._hk_code)
    assert len(out) == 14 and out[0] == "0001.HK"


def test_extract_none_when_no_column_has_enough():
    tables = [_FakeTable(["Company"], [("Acme",)])]
    assert idx._extract(tables, ("symbol", "ticker"), idx._us_code) is None


def test_merge_dedupes_and_none_on_all_empty():
    assert idx._merge(["A", "B"], ["B", "C"]) == ["A", "B", "C"]
    assert idx._merge(None, None) is None
    assert idx._merge([], None) is None


# ---------------------------------------------------------------------------
# offline tripwire — guard_online is OUTSIDE _wiki_tables' try, so it must
# propagate (a swallowed None here degraded the scan silently for days).
# ---------------------------------------------------------------------------
def test_wiki_tables_offline_raises():
    with pytest.raises(OfflineError):
        idx._wiki_tables("List_of_S%26P_500_companies")


def test_universe_fns_propagate_offline_tripwire(tmp_path):
    from app.data.base import DiskTTLCache
    idx._cache = DiskTTLCache(root=str(tmp_path))
    with pytest.raises(OfflineError):
        idx.us_universe()
    with pytest.raises(OfflineError):
        idx.hk_universe()
    with pytest.raises(OfflineError):
        idx.sg_universe()


# ---------------------------------------------------------------------------
# audit_against_ibkr (unchanged)
# ---------------------------------------------------------------------------
def test_audit_against_ibkr_unavailable_returns_none(monkeypatch):
    import app.brokers.ibkr_client as ibkr
    monkeypatch.setattr(ibkr, "qualify_symbols", lambda specs: None)
    assert idx.audit_against_ibkr(["AAPL"], "US") is None
    assert idx.audit_against_ibkr([], "US") is None
    assert idx.audit_against_ibkr(["AAPL"], "JP") is None  # no IBKR mapping


def test_audit_against_ibkr_splits_and_builds_specs(monkeypatch):
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
