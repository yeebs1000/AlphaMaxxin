"""HKEX/SGX universe adapters — fixture-tested offline.

The brief allows the broader exchange adapter only if its format is stable and
fixture-tested. The fixtures below mirror the real feeds row-for-row (shapes
captured from live responses on 2026-09-07): the HKEX sheet's Category /
Sub-Category / Shortsell Eligible columns, and SGX's typed rows.
"""
import pytest

from app.data import exchange_universes as eu


# ---------------------------------------------------------------------------
# HKEX
# ---------------------------------------------------------------------------
HKEX_ROWS = [
    # ordinary Main Board, shortsell-eligible -> in
    {"Stock Code": 1, "Name of Securities": "CKH HOLDINGS", "Category": "Equity",
     "Sub-Category": "Equity Securities (Main Board)", "Shortsell Eligible": "Y",
     "ISIN": "KYG217651051"},
    {"Stock Code": 700, "Name of Securities": "TENCENT", "Category": "Equity",
     "Sub-Category": "Equity Securities (Main Board)", "Shortsell Eligible": "Y",
     "ISIN": "KYG875721634"},
    # Main Board but NOT shortsell-eligible -> out (the liquidity screen)
    {"Stock Code": 8, "Name of Securities": "PCCW", "Category": "Equity",
     "Sub-Category": "Equity Securities (Main Board)", "Shortsell Eligible": " "},
    # GEM -> out
    {"Stock Code": 8001, "Name of Securities": "SOME GEM CO", "Category": "Equity",
     "Sub-Category": "Equity Securities (GEM)", "Shortsell Eligible": "Y"},
    # structured products and debt -> out
    {"Stock Code": 12345, "Name of Securities": "BOCI-CALL", "Category":
     "Derivative Warrants", "Sub-Category": "", "Shortsell Eligible": " "},
    {"Stock Code": 60001, "Name of Securities": "CBBC", "Category":
     "Callable Bull/Bear Contracts", "Sub-Category": "", "Shortsell Eligible": " "},
    {"Stock Code": 4200, "Name of Securities": "A BOND", "Category":
     "Debt Securities", "Sub-Category": "", "Shortsell Eligible": " "},
    {"Stock Code": 2800, "Name of Securities": "TRACKER FUND", "Category":
     "Exchange Traded Products", "Sub-Category": "", "Shortsell Eligible": "Y"},
    # REIT -> only with the explicit flag
    {"Stock Code": 823, "Name of Securities": "LINK REIT", "Category":
     "Real Estate Investment Trusts", "Sub-Category": "", "Shortsell Eligible": "Y"},
]


def test_hkex_keeps_only_liquid_main_board_equities():
    rows = eu.parse_hkex_records(HKEX_ROWS)
    assert eu.tickers(rows) == ["0001.HK", "0700.HK"]
    assert all(r["stock_type"] == "common" for r in rows)
    assert rows[0]["universe_source"] == "hkex_list_of_securities"


def test_hkex_shortsell_flag_is_the_liquidity_screen():
    """PCCW is a real Main Board equity; it is excluded only because HKEX has
    not designated it shortsell-eligible. That designation is the exchange's
    own market-cap/turnover judgement, which is why it is used here instead of
    a threshold invented in this file."""
    assert "0008.HK" not in eu.tickers(eu.parse_hkex_records(HKEX_ROWS))


def test_hkex_excludes_derivatives_debt_and_etfs():
    tickers = eu.tickers(eu.parse_hkex_records(HKEX_ROWS))
    for excluded in ("12345.HK", "60001.HK", "4200.HK", "2800.HK", "8001.HK"):
        assert excluded not in tickers


def test_hkex_reits_are_an_explicit_decision():
    assert "0823.HK" not in eu.tickers(eu.parse_hkex_records(HKEX_ROWS))
    with_reits = eu.parse_hkex_records(HKEX_ROWS, include_reits=True)
    assert "0823.HK" in eu.tickers(with_reits)
    assert [r for r in with_reits if r["ticker"] == "0823.HK"][0]["stock_type"] == "reit"


@pytest.mark.parametrize("code,expected", [
    (1, "0001.HK"), (700, "0700.HK"), ("0005", "0005.HK"), (9999, "9999.HK"),
    (10000, None),        # 5-digit codes are structured products
    (0, None), ("", None), (None, None), ("abc", None),
])
def test_hk_ticker_normalization(code, expected):
    assert eu.hk_ticker(code) == expected


def test_hkex_deduplicates_and_sorts():
    rows = eu.parse_hkex_records(HKEX_ROWS + [HKEX_ROWS[0]])
    assert eu.tickers(rows) == sorted(eu.tickers(rows))
    assert len(rows) == len(set(eu.tickers(rows)))


def test_hkex_empty_or_garbage_input_yields_an_empty_universe():
    assert eu.parse_hkex_records([]) == []
    assert eu.parse_hkex_records(None) == []
    assert eu.parse_hkex_records([{"nonsense": 1}]) == []


# ---------------------------------------------------------------------------
# SGX
# ---------------------------------------------------------------------------
SGX_PAYLOAD = {"data": {"prices": [
    {"nc": "D05", "n": "DBS", "type": "stocks"},
    {"nc": "O39", "n": "OCBC Bank", "type": "stocks"},
    {"nc": "BQC", "n": "A-Smart", "type": "stocks"},
    {"nc": "A17U", "n": "CapLand Ascendas REIT", "type": "reits"},
    {"nc": "NS8U", "n": "Hutchison Port", "type": "businesstrusts"},
    {"nc": "ES3", "n": "STI ETF", "type": "etfs"},
    {"nc": "TATD", "n": "Tata Motors ADR", "type": "adrs"},
    {"nc": "XYZW", "n": "Some Warrant", "type": "structuredwarrants"},
    {"nc": "ABCD", "n": "A DLC", "type": "dlcertificates"},
    {"nc": None, "n": None, "type": "listedcertificates"},
    {"nc": "QQQQ", "n": "Unknown Kind", "type": "brand_new_type"},
]}}


def test_sgx_keeps_only_stocks_by_default():
    rows = eu.parse_sgx_payload(SGX_PAYLOAD)
    assert eu.tickers(rows) == ["BQC.SI", "D05.SI", "O39.SI"]


def test_sgx_reits_and_business_trusts_are_an_explicit_decision():
    """Economically central in Singapore, but they need their own factor
    profile before they can be ranked against operating companies."""
    rows = eu.parse_sgx_payload(SGX_PAYLOAD, include_reits=True)
    assert "A17U.SI" in eu.tickers(rows) and "NS8U.SI" in eu.tickers(rows)
    assert [r for r in rows if r["ticker"] == "A17U.SI"][0]["stock_type"] == "reit"


def test_sgx_excludes_etfs_adrs_warrants_and_certificates():
    tickers = eu.tickers(eu.parse_sgx_payload(SGX_PAYLOAD, include_reits=True))
    for excluded in ("ES3.SI", "TATD.SI", "XYZW.SI", "ABCD.SI"):
        assert excluded not in tickers


def test_sgx_unknown_type_is_excluded_not_assumed_equity():
    """An unrecognised type is not an equity until a human has looked at it."""
    assert "QQQQ.SI" not in eu.tickers(eu.parse_sgx_payload(SGX_PAYLOAD))


def test_sgx_null_codes_do_not_produce_ghost_tickers():
    assert all(r["ticker"] and "NONE" not in r["ticker"].upper()
               for r in eu.parse_sgx_payload(SGX_PAYLOAD))


def test_sgx_malformed_payloads_yield_an_empty_universe():
    for payload in (None, {}, {"data": {}}, {"data": {"prices": None}}):
        assert eu.parse_sgx_payload(payload) == []


@pytest.mark.parametrize("code,expected", [
    ("D05", "D05.SI"), ("a17u", "A17U.SI"), ("1Y1", "1Y1.SI"),
    ("TOOLONG", None), ("", None), (None, None), ("A-B", None),
])
def test_sg_ticker_normalization(code, expected):
    assert eu.sg_ticker(code) == expected


# ---------------------------------------------------------------------------
# network discipline
# ---------------------------------------------------------------------------
def test_fetchers_respect_the_offline_tripwire(monkeypatch):
    """ALPHAMAXXIN_OFFLINE=1 must stop these at the door, like every other
    provider in the tree."""
    from app.data.base import OfflineError
    monkeypatch.setenv("ALPHAMAXXIN_OFFLINE", "1")
    with pytest.raises(OfflineError):
        eu._http_get_bytes(eu.HKEX_URL)
    with pytest.raises(OfflineError):
        eu._http_get_json(eu.SGX_URL)


def test_a_failed_fetch_returns_none_rather_than_a_shrunken_universe(monkeypatch, tmp_path):
    """A silently smaller universe is worse than no universe: the caller can
    fall back to the index list, but it cannot detect a partial one."""
    from app.data.base import DiskTTLCache
    monkeypatch.setattr(eu, "_http_get_bytes",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert eu.hkex_universe(cache=DiskTTLCache(tmp_path)) is None
    monkeypatch.setattr(eu, "_http_get_json",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert eu.sgx_universe(cache=DiskTTLCache(tmp_path)) is None
