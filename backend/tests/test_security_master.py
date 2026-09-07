"""Security master: symbol normalization, identity/dedup, the two-level
IBKR/Yahoo taxonomy contract, conflict reporting, resumable merge, cache TTLs,
and the read-only settings of the contract-details adapter.

Offline by construction — nothing here touches a network, a gateway or a clock.
Every `now` is supplied, which is why the TTL tests can be exact instead of
sleeping.
"""
import pytest

from app.brokers import ibkr_client
from app.data import security_master as sm


# ---------------------------------------------------------------------------
# 1. universe normalization for US, HK and SG symbols
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,region,expected", [
    ("AAPL", "US", "AAPL"),
    ("BRK.B", "US", "BRK-B"),          # share class -> project convention
    ("  msft ", "US", "MSFT"),
    ("TOOLONGSYM", "US", None),
    ("700", "HK", "0700.HK"),          # zero-padded to four digits
    ("0700", "HK", "0700.HK"),
    ("SEHK:\xa0388", "HK", "0388.HK"),  # non-breaking space and prefix stripped
    ("", "HK", None),
    ("D05", "SG", "D05.SI"),
    ("SGX: A17U", "SG", "A17U.SI"),
    ("a17u", "SG", "A17U.SI"),
    ("TOOLONG", "SG", None),
    ("AAPL", "JP", None),              # region out of Phase 1 scope
    (None, "US", None),
])
def test_symbol_normalization(raw, region, expected):
    assert sm.normalize_symbol(raw, region) == expected


@pytest.mark.parametrize("ticker,expected", [
    ("AAPL", "US"), ("BRK-B", "US"),
    ("0700.HK", "HK"), ("0005.hk", "HK"),
    ("D05.SI", "SG"), ("a17u.si", "SG"),
    ("7203.T", None),        # Tokyo — outside Phase 1
    ("005930.KS", None),     # Seoul
    ("600519.SS", None),     # Shanghai
    ("", None), (None, None), (123, None),
])
def test_region_is_inferred_from_the_ticker_not_the_request(ticker, expected):
    """Region must never be inherited from the scope a caller asked for. The
    first live probe run pooled 2020.HK, 7203.T and 9961.HK into a `--region
    US` distribution because it assumed the requested region — this is the
    guard against that returning."""
    assert sm.region_for_ticker(ticker) == expected


def test_hk_and_sg_symbols_do_not_collide_across_regions():
    """Same digits, different region, different instrument. Identity must not
    depend on ticker text alone."""
    assert sm.normalize_symbol("5", "HK") == "0005.HK"
    assert sm.normalize_symbol("5", "SG") == "5.SI"


# ---------------------------------------------------------------------------
# 2. conId-first dedup and duplicate-symbol handling
# ---------------------------------------------------------------------------
def test_identity_prefers_con_id_over_ticker():
    assert sm.identity_key({"con_id": 265598, "region": "US", "ticker": "AAPL"}) \
        == "conId:265598"
    assert sm.identity_key({"region": "US", "ticker": "AAPL"}) == "US:AAPL"


def test_dedupe_is_con_id_first_and_reports_what_it_dropped():
    rows = [
        {"con_id": 1, "region": "US", "ticker": "AAPL"},
        {"con_id": 1, "region": "US", "ticker": "AAPL.OLD"},  # same instrument
        {"con_id": 2, "region": "HK", "ticker": "0700.HK"},
        {"region": "SG", "ticker": "D05.SI"},
        {"region": "SG", "ticker": "D05.SI"},                 # dup without conId
    ]
    unique, dupes = sm.dedupe_rows(rows)
    assert [r["ticker"] for r in unique] == ["AAPL", "0700.HK", "D05.SI"]
    # Dropped rows are reported, never silently swallowed.
    assert len(dupes) == 2
    assert dupes[0] == {"identity": "conId:1", "kept": "AAPL", "dropped": "AAPL.OLD"}


def test_same_ticker_different_region_is_not_a_duplicate():
    unique, dupes = sm.dedupe_rows([
        {"region": "US", "ticker": "C"}, {"region": "SG", "ticker": "C"}])
    assert len(unique) == 2 and dupes == []


# ---------------------------------------------------------------------------
# 3. IBKR industry -> canonical sector, category -> canonical industry
# ---------------------------------------------------------------------------
def test_source_field_contract_is_the_documented_one():
    """The providers name their levels differently; this mapping is the whole
    point of the module and a silent flip would misfile the entire universe."""
    assert sm.SOURCE_FIELD_CONTRACT["ibkr"] == {
        "sector": "ibkr_industry", "industry": "ibkr_category"}
    assert sm.SOURCE_FIELD_CONTRACT["yahoo"] == {
        "sector": "yahoo_sector", "industry": "yahoo_industry"}


def test_ibkr_industry_becomes_canonical_sector():
    resolved = sm.resolve_taxonomy({"ibkr_industry": "Consumer, Cyclical"})
    assert resolved["sector"] == "Consumer Cyclical"
    assert resolved["sector_status"] == "ibkr_only"


def test_raw_provider_fields_are_retained_verbatim_and_not_renamed():
    row = {"ibkr_industry": "Technology", "ibkr_category": "Semiconductors",
           "yahoo_sector": "Technology", "yahoo_industry": "Semiconductors"}
    resolved = sm.resolve_taxonomy(row)
    for field in sm.RETAINED_RAW_FIELDS:
        assert resolved[field] == row[field], f"{field} was altered or dropped"


def test_subcategory_is_never_read_or_persisted():
    """The feature has exactly two levels. A third would invite ranking on it."""
    class FakeContract:
        conId, symbol, localSymbol = 4391, "AAPL", "AAPL"
        primaryExchange, currency = "NASDAQ", "USD"

    class FakeDetails:
        contract = FakeContract()
        longName, stockType = "APPLE INC", "COMMON"
        industry, category = "Technology", "Computers"
        subcategory = "Computers-Personal"     # must be ignored entirely

    row = ibkr_client.taxonomy_row_from_details(FakeDetails(), key="AAPL")
    assert "subcategory" not in row
    assert "Computers-Personal" not in str(row)
    assert row["ibkr_industry"] == "Technology"   # -> sector
    assert row["ibkr_category"] == "Computers"    # -> industry
    assert row["con_id"] == 4391 and row["stock_type"] == "COMMON"


def test_ibkr_category_has_no_approved_crosswalk_yet():
    """Phase 1 deliberately ships an EMPTY IBKR industry crosswalk: preferring
    IBKR at industry level is blocked until a measured coverage audit produces
    a vocabulary the owner has approved. Every row therefore falls back to
    Yahoo for industry, and the audit reporting that is the finding, not a bug.
    """
    assert sm._IBKR_INDUSTRY_ALIASES == {}
    resolved = sm.resolve_taxonomy(
        {"ibkr_industry": "Technology", "ibkr_category": "Semiconductors",
         "yahoo_sector": "Technology", "yahoo_industry": "Semiconductors"})
    assert resolved["sector_status"] == "both_agree"
    assert resolved["industry"] == "Semiconductors"
    assert resolved["industry_status"] == "yahoo_fallback"


def test_unknown_labels_are_unmapped_never_guessed():
    resolved = sm.resolve_taxonomy({"ibkr_industry": "Consumer, Non-cyclical"})
    # Deliberately unmapped: it spans Yahoo's Consumer Defensive AND Healthcare.
    assert resolved["sector"] is None
    assert resolved["sector_status"] == "unmapped"


def test_label_form_normalization_does_not_change_meaning():
    assert sm.canonical_sector("  financial   services ", "yahoo") == "Financial Services"
    assert sm.canonical_sector("Health Care", "yahoo") == "Healthcare"
    assert sm.canonical_sector("Consumer  Cyclical", "yahoo") == "Consumer Cyclical"
    # Not a substring match: "Tech" must not resolve to "Technology".
    assert sm.canonical_sector("Tech", "yahoo") is None
    assert sm.canonical_sector("Technology Hardware Superconductors", "yahoo") is None


# ---------------------------------------------------------------------------
# 4. Yahoo fallback plus explicit conflict reporting
# ---------------------------------------------------------------------------
def test_yahoo_fallback_when_ibkr_absent():
    resolved = sm.resolve_taxonomy({"yahoo_sector": "Energy",
                                    "yahoo_industry": "Oil & Gas Midstream"})
    assert resolved["sector"] == "Energy"
    assert resolved["sector_status"] == "yahoo_fallback"
    assert resolved["sector_source"] == "yahoo"
    assert resolved["taxonomy_conflict"] is False


def test_conflict_is_reported_not_reconciled():
    """Both providers mapped and disagreed. Keep both raws, flag the row, and
    do not force agreement — a forced label is an invented fact."""
    resolved = sm.resolve_taxonomy({"ibkr_industry": "Technology",
                                    "yahoo_sector": "Industrials"})
    assert resolved["sector_status"] == "taxonomy_conflict"
    assert resolved["taxonomy_conflict"] is True
    assert resolved["sector"] == "Technology"          # preferred source wins
    assert resolved["ibkr_industry"] == "Technology"   # both raws survive
    assert resolved["yahoo_sector"] == "Industrials"


def test_agreement_is_reported_when_both_map_the_same():
    resolved = sm.resolve_taxonomy({"ibkr_industry": "Energy",
                                    "yahoo_sector": "Energy"})
    assert resolved["sector_status"] == "both_agree"
    assert resolved["taxonomy_conflict"] is False


def test_prefer_yahoo_flips_precedence_without_changing_the_raws():
    row = {"ibkr_industry": "Technology", "yahoo_sector": "Industrials"}
    resolved = sm.resolve_taxonomy(row, prefer="yahoo")
    assert resolved["sector"] == "Industrials"
    assert resolved["sector_status"] == "taxonomy_conflict"
    assert resolved["ibkr_industry"] == "Technology"


# ---------------------------------------------------------------------------
# industry groups
# ---------------------------------------------------------------------------
def test_every_table_key_survives_its_own_normalization():
    """The regression guard for a real bug: the table is written with "&" for
    readability, normalize_label_form rewrites "&" to " and ", and the lookup
    silently missed 42 of 143 labels — every ampersand one, including
    Aerospace & Defense and Oil & Gas E&P. Both sides must normalize alike."""
    unresolvable = [label for label in sm.INDUSTRY_GROUPS
                    if not sm.industry_group(label)]
    assert unresolvable == []


@pytest.mark.parametrize("industry,group", [
    ("Aerospace & Defense", "Aerospace & Defense"),
    ("Oil & Gas E&P", "Oil & Gas Upstream"),
    ("Auto Parts", "Automotive"),
    ("Restaurants", "Hospitality & Leisure"),
    ("Semiconductors", "Semiconductors & Equipment"),
    ("Banks - Regional", "Banks"),
    ("aerospace and defense", "Aerospace & Defense"),   # case/ampersand forms
])
def test_industry_group_mapping(industry, group):
    assert sm.industry_group(industry) == group


def test_unknown_industry_has_no_group():
    assert sm.industry_group("Underwater Basket Weaving") is None
    assert sm.industry_group(None) is None
    assert sm.industry_group("") is None


def test_group_table_is_a_coarsening_not_a_renaming():
    """A group that contains exactly one industry buys nothing; the tier only
    earns its place by merging fragments."""
    from collections import Counter
    sizes = Counter(sm.INDUSTRY_GROUPS.values())
    merged = [g for g, n in sizes.items() if n > 1]
    assert len(merged) >= 25, "most groups should merge several industries"
    assert len(sizes) < len(sm.INDUSTRY_GROUPS)


def test_build_row_exposes_the_group_and_its_version():
    row = sm.build_row({"region": "US", "ticker": "AAPL",
                        "yahoo_sector": "Technology",
                        "yahoo_industry": "Consumer Electronics"})
    assert row["industry_group"] == "Hardware & Components"
    assert row["industry_group_version"] == sm.INDUSTRY_GROUP_VERSION


# ---------------------------------------------------------------------------
# inclusion rules
# ---------------------------------------------------------------------------
def test_non_equity_instruments_are_excluded():
    for stock_type in ("WARRANT", "ETF", "Bond", "right"):
        row = sm.build_row({"region": "US", "ticker": "X", "stock_type": stock_type})
        assert row["included"] is False, stock_type


def test_reits_and_catalist_are_explicit_decisions_not_silent_drops():
    reit = {"region": "SG", "ticker": "A17U.SI", "stock_type": "REIT"}
    assert sm.build_row(reit)["included"] is False
    assert sm.build_row(reit, include_reits=True)["included"] is True
    catalist = {"region": "SG", "ticker": "ABC.SI", "stock_type": "common",
                "board": "Catalist"}
    assert sm.build_row(catalist)["included"] is False
    assert sm.build_row(catalist, include_catalist=True)["included"] is True


def test_missing_stock_type_is_missing_data_not_an_exclusion():
    row = sm.build_row({"region": "US", "ticker": "AAPL"})
    assert row["included"] is True and row["exclusions"] == []


# ---------------------------------------------------------------------------
# 5. incremental/resumable merge and positive/negative cache expiry
# ---------------------------------------------------------------------------
def test_partial_refresh_never_shrinks_the_universe():
    existing = [{"region": "US", "ticker": "AAPL", "con_id": 1, "long_name": "Apple"},
                {"region": "US", "ticker": "MSFT", "con_id": 2},
                {"region": "HK", "ticker": "0700.HK", "con_id": 3}]
    merged = sm.merge_universe(existing, [{"con_id": 2, "long_name": "Microsoft"}],
                               failures=["conId:3"])
    assert len(merged["rows"]) == 3, "an interrupted pass must not drop rows"
    assert merged["refreshed"] == 1 and merged["carried_forward"] == 2
    assert merged["failed"] == ["conId:3"]
    by_id = {r["con_id"]: r for r in merged["rows"]}
    assert by_id[2]["long_name"] == "Microsoft"     # incoming wins
    assert by_id[1]["long_name"] == "Apple"         # untouched row survives


def test_incoming_nulls_do_not_blank_established_values():
    merged = sm.merge_universe(
        [{"con_id": 1, "region": "US", "ticker": "AAPL", "ibkr_industry": "Technology"}],
        [{"con_id": 1, "region": "US", "ticker": "AAPL", "ibkr_industry": None}])
    assert merged["rows"][0]["ibkr_industry"] == "Technology"


def test_merge_does_not_mutate_its_inputs():
    existing = [{"con_id": 1, "region": "US", "ticker": "AAPL"}]
    incoming = [{"con_id": 1, "region": "US", "ticker": "AAPL", "long_name": "Apple"}]
    before = (repr(existing), repr(incoming))
    sm.merge_universe(existing, incoming)
    assert (repr(existing), repr(incoming)) == before


def test_positive_and_negative_cache_ttls_differ_and_expire():
    ok = sm.make_cache_record("AAPL", {"x": 1}, now=1000.0, ok=True, source="ibkr")
    bad = sm.make_cache_record("ZZZZ", None, now=1000.0, ok=False, source="ibkr")
    assert ok["ttl_s"] == sm.POSITIVE_TTL_S == 30 * 86400
    assert bad["ttl_s"] == sm.NEGATIVE_TTL_S == 24 * 3600
    assert bad["payload"] is None
    assert sm.cache_record_fresh(ok, now=1000.0 + 29 * 86400) is True
    assert sm.cache_record_fresh(ok, now=1000.0 + 31 * 86400) is False
    assert sm.cache_record_fresh(bad, now=1000.0 + 23 * 3600) is True
    assert sm.cache_record_fresh(bad, now=1000.0 + 25 * 3600) is False
    assert sm.cache_record_fresh(None, now=1000.0) is False
    assert sm.cache_record_fresh({"fetched_at": "nope", "ttl_s": 1}, now=1.0) is False


# ---------------------------------------------------------------------------
# 6. read-only IBKR connection settings, zero startup account/order fetches
# ---------------------------------------------------------------------------
def test_contract_details_connection_is_read_only():
    kwargs = ibkr_client.contract_details_connect_kwargs()
    assert kwargs["readonly"] is True


def test_contract_details_performs_no_startup_account_or_order_fetch():
    """ib_async's handshake fetches positions, open/completed orders, account
    updates and executions by default. StartupFetchNONE turns all of that off —
    this adapter is allowed to read contract metadata and nothing else."""
    kwargs = ibkr_client.contract_details_connect_kwargs()
    fetch_fields = kwargs.get("fetchFields")
    assert fetch_fields is not None, "ib_async without StartupFetch — re-check"
    assert not list(fetch_fields), f"startup fetch requests {fetch_fields!r}"


def test_taxonomy_uses_a_client_id_distinct_from_positions_and_qualify():
    """A shared client id silently steals another session's connection, and one
    of those sessions is the live portfolio sync."""
    ids = {ibkr_client.IBKR_CLIENT_ID,             # positions / account summary
           ibkr_client.IBKR_CLIENT_ID + 1,         # qualify_symbols
           ibkr_client.IBKR_TAXONOMY_CLIENT_ID}
    assert len(ids) == 3
    assert ibkr_client.contract_details_connect_kwargs()["clientId"] == \
        ibkr_client.IBKR_TAXONOMY_CLIENT_ID


def test_taxonomy_fetch_is_bounded_and_serialized():
    assert ibkr_client._TAXONOMY_MAX_REQUESTS <= 500
    assert ibkr_client._TAXONOMY_PAUSE_S > 0, "requests must not burst the gateway"


def test_taxonomy_fetch_returns_none_when_gateway_unreachable(monkeypatch):
    """No gateway must mean 'no data', never an exception into the caller."""
    monkeypatch.setattr(ibkr_client, "_gateway_reachable", lambda: False)
    assert ibkr_client.fetch_contract_taxonomy(
        [{"key": "AAPL", "symbol": "AAPL", "exchange": "SMART", "currency": "USD"}]) is None
    assert ibkr_client.fetch_contract_taxonomy([]) is None


# ---------------------------------------------------------------------------
# end-to-end row build and coverage audit
# ---------------------------------------------------------------------------
def test_build_row_carries_identity_and_provenance():
    row = sm.build_row({
        "region": "HK", "source_symbol": "700", "universe_source": "hang_seng",
        "universe_source_version": "2026-09-06", "con_id": 12345,
        "local_symbol": "700", "primary_exchange": "SEHK", "currency": "HKD",
        "long_name": "TENCENT HOLDINGS LTD", "stock_type": "COMMON",
        "ibkr_industry": "Communications", "ibkr_category": "Internet",
        "yahoo_sector": "Communication Services", "yahoo_industry": "Internet Content",
    })
    assert row["ticker"] == "0700.HK"
    assert row["sector"] == "Communication Services"
    assert row["sector_status"] == "both_agree"
    assert row["industry"] == "Internet Content"        # Yahoo, per the audit gap
    assert row["identity"] == "conId:12345"
    assert row["schema_version"] == sm.SCHEMA_VERSION
    assert row["included"] is True


def test_coverage_audit_reports_the_numbers_the_owner_asked_for():
    rows = [
        sm.build_row({"region": "US", "ticker": "AAPL", "ibkr_industry": "Technology",
                      "yahoo_sector": "Technology", "yahoo_industry": "Consumer Electronics",
                      "con_id": 1}),
        sm.build_row({"region": "US", "ticker": "XOM", "ibkr_industry": "Technology",
                      "yahoo_sector": "Energy", "yahoo_industry": "Oil and Gas"}),
        sm.build_row({"region": "SG", "ticker": "D05.SI",
                      "ibkr_industry": "Wildly Unknown Label"}),
    ]
    audit = sm.coverage_audit(rows, duplicates=[{"identity": "conId:9"}],
                              elapsed_s=1.5, errors=["one timeout"])
    assert audit["rows_in"] == 3
    assert audit["by_region"] == {"US": 2, "SG": 1}
    assert audit["sector_fill_rate"] == round(2 / 3, 4)
    assert audit["taxonomy_conflict_count"] == 1        # XOM: Technology vs Energy
    assert audit["con_id_fill_rate"] == round(1 / 3, 4)
    assert audit["duplicate_count"] == 1
    assert audit["errors"] == ["one timeout"]
    assert audit["elapsed_s"] == 1.5
    # The unmapped label is surfaced by name so the owner can approve a mapping.
    assert "Wildly Unknown Label" in audit["unmapped_raw_labels"]["sector"]
    assert audit["taxonomy_version"] == sm.TAXONOMY_VERSION


def test_coverage_audit_on_empty_input_does_not_divide_by_zero():
    audit = sm.coverage_audit([])
    assert audit["rows_in"] == 0 and audit["sector_fill_rate"] is None


# ---------------------------------------------------------------------------
# inertness: this module must stay usable without a network or a clock
# ---------------------------------------------------------------------------
def test_security_master_imports_nothing_that_reaches_the_world():
    import inspect
    source = inspect.getsource(sm)
    for banned in ("import os", "import time", "import requests", "import urllib",
                   "from pathlib", "import socket", "datetime"):
        assert banned not in source, f"security_master reaches {banned}"
