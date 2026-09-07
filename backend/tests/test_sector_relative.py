"""Sector-relative kernel: determinism, permutation invariance, tie handling,
factor direction, invalid-value handling, weight renormalization, peer-level
policy, per-factor denominators, input immutability, JSON safety, the module's
inertness, and the probe's offline guarantee.

Fixtures are hand-calculable on purpose. With MIN_PEERS=12 and twelve distinct
values the midrank percentile of the smallest is (1 - 0.5) / 12 * 100 =
4.1667, so a `lower_is_better` factor scores it 95.8333 — every expectation
below is arithmetic a reader can check without running the code.
"""
import copy
import importlib.util
import inspect
import io
import json
import random
import tokenize
from pathlib import Path

import pytest

from app.skills import sector_relative as sr

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "scripts" / "sector_relative_probe.py"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def snapshot(ticker, *, sector="Technology", industry="Semiconductors",
             fwd_pe=None, ev_ebitda=None, ps=None, rev_yoy=None, eps_yoy=None,
             op_margin=None, net_margin=None, f_score=None):
    snap = {
        "ticker": ticker, "sector": sector, "industry": industry,
        "valuation": {"fwd_pe": fwd_pe, "ev_ebitda": ev_ebitda, "ps": ps},
        "growth": {"rev_yoy": rev_yoy, "eps_yoy": eps_yoy},
        "margins": {"operating": op_margin, "net": net_margin},
    }
    if f_score is not None:
        snap["f_score"] = f_score
    return snap


VALUE_ONLY = {
    "id": "value-only-test", "version": "t1", "min_families": 1,
    "family_weights": {"value": 1.0},
    "factors": ({"id": "fwd_pe", "family": "value",
                 "source": "fundamentals:valuation.fwd_pe",
                 "direction": "lower_is_better", "weight": 1.0,
                 "require_positive": True, "version": "t1"},),
}

GROWTH_ONLY = {
    "id": "growth-only-test", "version": "t1", "min_families": 1,
    "family_weights": {"growth": 1.0},
    "factors": ({"id": "rev_yoy", "family": "growth",
                 "source": "fundamentals:growth.rev_yoy",
                 "direction": "higher_is_better", "weight": 1.0, "version": "t1"},),
}

THREE_FAMILY = {
    "id": "three-family-test", "version": "t1", "min_families": 2,
    "family_weights": {"value": 3.0, "growth": 1.0, "quality": 1.0},
    "factors": (
        {"id": "fwd_pe", "family": "value", "source": "fundamentals:valuation.fwd_pe",
         "direction": "lower_is_better", "weight": 1.0, "require_positive": True,
         "version": "t1"},
        {"id": "rev_yoy", "family": "growth", "source": "fundamentals:growth.rev_yoy",
         "direction": "higher_is_better", "weight": 1.0, "version": "t1"},
        {"id": "op_margin", "family": "quality", "source": "fundamentals:margins.operating",
         "direction": "higher_is_better", "weight": 1.0, "version": "t1"},
    ),
}


def twelve_semis(**overrides):
    """T01..T12 in one industry: fwd_pe 11..22, rev_yoy 0.01..0.12."""
    names = {}
    for i in range(1, 13):
        ticker = f"T{i:02d}"
        names[ticker] = snapshot(ticker, fwd_pe=10 + i, rev_yoy=0.01 * i,
                                 op_margin=0.01 * i)
    names.update(overrides)
    return names


def twelve_us_semis():
    """TA..TL — letter-only, so the probe's region inference sees real US
    tickers. Same twelve-name shape as twelve_semis()."""
    return {f"T{chr(64 + i)}": snapshot(f"T{chr(64 + i)}", fwd_pe=10 + i,
                                        rev_yoy=0.01 * i, op_margin=0.01 * i)
            for i in range(1, 13)}


def analyze(fundamentals, profile=VALUE_ONLY, bars=None, sector="Technology",
            as_of="2026-09-06", taxonomy=None, groups=None):
    return sr.analyze_sector_relative(
        fundamentals, bars or {}, region="US", sector=sector, as_of=as_of,
        profile=profile, taxonomy_by_ticker=taxonomy,
        industry_groups=groups if groups is not None else SEMI_GROUPS)


def rows_by_ticker(result):
    return {r["ticker"]: r for r in result["candidates"]}


# ---------------------------------------------------------------------------
# 7. deterministic output for identical input
# ---------------------------------------------------------------------------
def test_identical_input_gives_byte_identical_output():
    data = twelve_semis()
    first = json.dumps(analyze(data), sort_keys=True)
    second = json.dumps(analyze(copy.deepcopy(data)), sort_keys=True)
    assert first == second


# ---------------------------------------------------------------------------
# 8. input-order / permutation invariance
# ---------------------------------------------------------------------------
def test_output_does_not_depend_on_input_ordering():
    """A ranking that moves when the caller reorders its dict is not a ranking."""
    data = twelve_semis()
    shuffled_keys = list(data)
    random.Random(20260906).shuffle(shuffled_keys)
    shuffled = {k: data[k] for k in shuffled_keys}
    assert json.dumps(analyze(data), sort_keys=True) == \
        json.dumps(analyze(shuffled), sort_keys=True)


# ---------------------------------------------------------------------------
# 9. stable tie handling and ticker tie-break
# ---------------------------------------------------------------------------
def test_ties_share_a_midrank_percentile():
    data = twelve_semis()
    data["T01"] = snapshot("T01", fwd_pe=11, rev_yoy=0.01)
    data["T02"] = snapshot("T02", fwd_pe=11, rev_yoy=0.02)   # tied with T01
    rows = rows_by_ticker(analyze(data))
    # Ranks 1 and 2 share midrank 1.5 -> (1.5 - 0.5) / 12 * 100 = 8.3333,
    # inverted for lower_is_better -> 91.6667.
    assert rows["T01"]["factor_percentiles"]["fwd_pe"] == pytest.approx(91.6667)
    assert rows["T02"]["factor_percentiles"]["fwd_pe"] == pytest.approx(91.6667)


def test_equal_scores_are_ordered_by_ticker():
    data = twelve_semis()
    data["T01"] = snapshot("T01", fwd_pe=11)
    data["T02"] = snapshot("T02", fwd_pe=11)
    ranked = [r["ticker"] for r in analyze(data)["candidates"]
              if r["experimental_score"] is not None]
    assert ranked[:2] == ["T01", "T02"]


def test_midrank_percentiles_helper_is_hand_checkable():
    assert sr.midrank_percentiles([("A", 1.0), ("B", 2.0)]) == {"A": 25.0, "B": 75.0}
    tied = sr.midrank_percentiles([("A", 1.0), ("B", 1.0), ("C", 3.0)])
    assert tied["A"] == tied["B"] == pytest.approx(100 * (1.5 - 0.5) / 3)
    assert tied["C"] == pytest.approx(100 * (3 - 0.5) / 3)


# ---------------------------------------------------------------------------
# 10. factor direction
# ---------------------------------------------------------------------------
def test_lower_is_better_scores_the_smallest_value_highest():
    rows = rows_by_ticker(analyze(twelve_semis()))
    assert rows["T01"]["factor_percentiles"]["fwd_pe"] == pytest.approx(95.8333)
    assert rows["T12"]["factor_percentiles"]["fwd_pe"] == pytest.approx(4.1667)
    assert rows["T01"]["experimental_rank"] == 1


def test_higher_is_better_scores_the_largest_value_highest():
    rows = rows_by_ticker(analyze(twelve_semis(), profile=GROWTH_ONLY))
    assert rows["T12"]["factor_percentiles"]["rev_yoy"] == pytest.approx(95.8333)
    assert rows["T01"]["factor_percentiles"]["rev_yoy"] == pytest.approx(4.1667)
    assert rows["T12"]["experimental_rank"] == 1


def test_a_factor_without_an_explicit_direction_is_skipped_and_warned():
    """Direction must be declared, never inferred from a field name."""
    profile = copy.deepcopy(VALUE_ONLY)
    profile["factors"] = ({**profile["factors"][0], "direction": None},)
    result = analyze(twelve_semis(), profile=profile)
    assert rows_by_ticker(result)["T01"]["factor_percentiles"] == {}
    assert any("no explicit direction" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# 11. invalid / non-positive valuation handling
# ---------------------------------------------------------------------------
def test_non_positive_multiple_is_not_treated_as_cheap():
    data = twelve_semis()
    data["T13"] = snapshot("T13", fwd_pe=-5.0)      # loss-making, not "cheapest"
    data["T14"] = snapshot("T14", fwd_pe=0.0)
    rows = rows_by_ticker(analyze(data))
    for ticker in ("T13", "T14"):
        assert "fwd_pe" not in rows[ticker]["factor_percentiles"]
        assert rows[ticker]["factor_coverage"]["fwd_pe"] == "non_positive"
        assert rows[ticker]["experimental_score"] is None
    # The genuinely cheapest real multiple keeps the top score.
    assert rows["T01"]["experimental_rank"] == 1


@pytest.mark.parametrize("bad", [None, "12", True, float("nan"), float("inf")])
def test_non_numeric_and_non_finite_values_are_missing_not_zero(bad):
    data = twelve_semis()
    data["T13"] = snapshot("T13", fwd_pe=bad)
    rows = rows_by_ticker(analyze(data))
    assert rows["T13"]["factor_coverage"]["fwd_pe"] in ("missing", "non_positive")
    assert "fwd_pe" not in rows["T13"]["factor_percentiles"]


def test_missing_values_are_excluded_never_imputed_to_neutral():
    """Imputing 50 would reward missing data, which is exactly backwards for
    the thin non-US coverage this universe has."""
    data = twelve_semis()
    data["T13"] = snapshot("T13")                     # no fields at all
    rows = rows_by_ticker(analyze(data))
    assert rows["T13"]["factor_percentiles"] == {}
    assert rows["T13"]["experimental_score"] is None
    assert 50.0 not in rows["T13"]["family_scores"].values()


# ---------------------------------------------------------------------------
# 12. missing-factor exclusion and weight renormalization
# ---------------------------------------------------------------------------
def test_composite_renormalizes_over_present_families_only():
    """Quality is absent for everyone, so the composite must be the
    value/growth weighted mean renormalized over weight 3 + 1, not a silent
    division by the full 5."""
    data = {t: snapshot(t, fwd_pe=10 + i, rev_yoy=0.01 * i)
            for i, t in enumerate((f"T{n:02d}" for n in range(1, 13)), start=1)}
    rows = rows_by_ticker(analyze(data, profile=THREE_FAMILY))
    row = rows["T01"]
    assert set(row["family_scores"]) == {"value", "growth"}
    expected = (3.0 * row["family_scores"]["value"]
                + 1.0 * row["family_scores"]["growth"]) / 4.0
    assert row["experimental_score"] == pytest.approx(expected, abs=1e-4)


def test_a_factor_missing_for_one_name_does_not_sink_the_others():
    # 13 names, so dropping one value still leaves 12 with fwd_pe and the pool
    # stays at MIN_PEERS. This isolates one NAME losing a factor from the
    # separate case of the whole factor falling below the threshold, which the
    # denominator test below covers.
    data = twelve_semis()
    data["T13"] = snapshot("T13", fwd_pe=23, rev_yoy=0.13, op_margin=0.13)
    data["T05"] = snapshot("T05", rev_yoy=0.05, op_margin=0.05)   # no fwd_pe
    rows = rows_by_ticker(analyze(data, profile=THREE_FAMILY))
    assert rows["T05"]["factor_denominators"]["fwd_pe"] == 12
    assert rows["T05"]["factor_coverage"]["fwd_pe"] == "missing"
    assert "value" not in rows["T05"]["family_scores"]
    assert rows["T01"]["experimental_score"] is not None


# ---------------------------------------------------------------------------
# 13. minimum family coverage before a composite is emitted
# ---------------------------------------------------------------------------
def test_composite_requires_the_profiles_minimum_family_count():
    data = {f"T{i:02d}": snapshot(f"T{i:02d}", fwd_pe=10 + i)
            for i in range(1, 13)}                 # value family only
    rows = rows_by_ticker(analyze(data, profile=THREE_FAMILY))
    assert rows["T01"]["family_scores"].keys() == {"value"}
    assert rows["T01"]["experimental_score"] is None
    assert any("of 2 required families" in w for w in rows["T01"]["warnings"])


def test_null_v1_requires_three_families():
    assert sr.NULL_V1_PROFILE["min_families"] == 3
    families = {f["family"] for f in sr.NULL_V1_PROFILE["factors"]}
    assert families == {"value", "growth", "quality", "price"}


def test_null_v1_declares_every_required_field_on_every_factor():
    for factor in sr.NULL_V1_PROFILE["factors"]:
        for field in ("id", "family", "source", "direction", "weight", "version"):
            assert field in factor, f"{factor.get('id')} missing {field}"
        assert factor["direction"] in ("higher_is_better", "lower_is_better")


# ---------------------------------------------------------------------------
# 14-16. peer-level policy
# ---------------------------------------------------------------------------
def test_industry_peers_are_used_at_twelve_or_more():
    rows = rows_by_ticker(analyze(twelve_semis()))
    assert rows["T01"]["peer_level_used"] == "industry"
    assert rows["T01"]["peer_count"] == 12
    assert rows["T01"]["peer_level_requested"] == "industry"


def test_thin_industry_falls_back_once_to_the_sector_pool():
    data = twelve_semis()
    for i in range(1, 4):                       # 3 software names, same sector
        ticker = f"S{i:02d}"
        data[ticker] = snapshot(ticker, industry="Software", fwd_pe=30 + i)
    rows = rows_by_ticker(analyze(data))
    assert rows["T01"]["peer_level_used"] == "industry" and rows["T01"]["peer_count"] == 12
    assert rows["S01"]["peer_level_used"] == "sector"
    assert rows["S01"]["peer_count"] == 15      # 12 semis + 3 software
    assert analyze(data)["coverage"]["peer_level_counts"] == {"industry": 12, "sector": 3}


SEMI_GROUPS = {"Semiconductors": "Semis & Equipment",
               "Semiconductor Equipment": "Semis & Equipment",
               "Software - Application": "Software"}


def test_thin_industry_uses_the_group_before_falling_to_sector():
    """The middle tier is the whole point: two 6-name industries that share a
    group form one 12-name pool instead of both collapsing into a sector pool
    that mixes them with everything else."""
    data = {}
    for i in range(1, 7):
        for industry in ("Semiconductors", "Semiconductor Equipment"):
            ticker = f"{'S' if industry == 'Semiconductors' else 'E'}{i:02d}"
            data[ticker] = snapshot(ticker, industry=industry, fwd_pe=10 + i)
    # 12 unrelated names keep the sector pool viable, so a fallback to sector
    # would also have "worked" — this proves the group tier is preferred.
    for i in range(1, 13):
        ticker = f"X{i:02d}"
        data[ticker] = snapshot(ticker, industry="Software - Application",
                                fwd_pe=40 + i)
    rows = rows_by_ticker(analyze(data, taxonomy=None, sector="Technology"))
    assert rows["S01"]["peer_level_used"] == "industry_group"
    assert rows["S01"]["peer_count"] == 12          # 6 semis + 6 equipment
    assert rows["S01"]["industry_group"] == "Semis & Equipment"
    # The 12 software names reach their own industry pool, not the group.
    assert rows["X01"]["peer_level_used"] == "industry"


def test_group_tier_is_skipped_when_the_industry_itself_qualifies():
    data = twelve_semis()
    rows = rows_by_ticker(analyze(data))
    assert rows["T01"]["peer_level_used"] == "industry"


def test_an_unmapped_industry_falls_through_to_sector_not_into_a_guess():
    data = twelve_semis()
    for i in range(1, 4):
        ticker = f"U{i:02d}"
        data[ticker] = snapshot(ticker, industry="Some Brand New Industry",
                                fwd_pe=30 + i)
    rows = rows_by_ticker(analyze(data))
    assert rows["U01"]["industry_group"] is None
    assert rows["U01"]["peer_level_used"] == "sector"


def test_coverage_reports_the_group_tier():
    data = twelve_semis()
    coverage = analyze(data)["coverage"]
    assert "industry_groups_present" in coverage
    assert "names_without_industry_group" in coverage


def test_peer_policy_documents_all_three_levels():
    policy = analyze(twelve_semis())["peer_policy"]
    assert policy["requested_level"] == "industry"
    assert policy["fallback_levels"] == ["industry_group", "sector"]


def test_no_score_when_every_allowed_level_is_below_the_minimum():
    data = {f"T{i:02d}": snapshot(f"T{i:02d}", fwd_pe=10 + i) for i in range(1, 6)}
    result = analyze(data)
    rows = rows_by_ticker(result)
    assert all(r["peer_level_used"] == "insufficient_peers" for r in rows.values())
    assert all(r["experimental_score"] is None for r in rows.values())
    assert result["coverage"]["insufficient_peer_groups"][0]["members"] == 5
    assert any("below MIN_PEERS" in w for w in result["warnings"])


def test_names_without_an_industry_label_use_the_sector_pool():
    data = twelve_semis()
    data["U01"] = snapshot("U01", industry=None, fwd_pe=15)
    rows = rows_by_ticker(analyze(data))
    assert rows["U01"]["peer_level_used"] == "sector"
    assert analyze(data)["coverage"]["names_without_industry"] == 1


def test_names_outside_the_requested_sector_are_excluded_and_reported():
    data = twelve_semis()
    data["E01"] = snapshot("E01", sector="Energy", industry="Oil", fwd_pe=8)
    result = analyze(data)
    assert "E01" not in rows_by_ticker(result)
    assert result["coverage"]["exclusions"]["E01"] == ["sector_mismatch"]
    assert result["coverage"]["in_scope_names"] == 12


def test_supplied_taxonomy_overrides_the_snapshot_label():
    """The security master, not the provider snapshot, is the classification
    authority once it has resolved a row."""
    data = twelve_semis()
    data["X01"] = snapshot("X01", sector="Energy", industry="Oil", fwd_pe=9)
    taxonomy = {"X01": {"sector": "Technology", "industry": "Semiconductors",
                        "sector_source": "ibkr", "sector_status": "ibkr_only",
                        "taxonomy_conflict": True, "taxonomy_version": "taxonomy-1"}}
    result = analyze(data, taxonomy=taxonomy)
    assert "X01" in rows_by_ticker(result)
    assert result["taxonomy"]["conflicts"] == ["X01"]
    assert result["taxonomy"]["version"] == "taxonomy-1"


# ---------------------------------------------------------------------------
# 17. per-factor denominators and coverage counts
# ---------------------------------------------------------------------------
def test_denominators_are_counted_per_factor_not_per_name():
    """Eligibility differs field by field: a name can have a P/E and no
    operating margin, so one shared denominator would be a fiction."""
    data = twelve_semis()
    for ticker in ("T01", "T02", "T03"):
        data[ticker] = snapshot(ticker, fwd_pe=10 + int(ticker[-2:]),
                                rev_yoy=0.01)          # op_margin dropped
    rows = rows_by_ticker(analyze(data, profile=THREE_FAMILY))
    assert rows["T04"]["factor_denominators"]["fwd_pe"] == 12
    assert rows["T04"]["factor_denominators"]["op_margin"] == 9
    # 9 < MIN_PEERS, so the quality factor scores nobody and says why.
    assert rows["T04"]["factor_coverage"]["op_margin"] == "insufficient_factor_peers"
    assert "quality" not in rows["T04"]["family_scores"]


def test_coverage_block_counts_missing_reasons_by_factor():
    data = twelve_semis()
    data["T13"] = snapshot("T13", fwd_pe=-1.0)
    data["T14"] = snapshot("T14")
    coverage = analyze(data)["coverage"]["missing_by_factor"]["fwd_pe"]
    assert coverage == {"missing": 1, "non_positive": 1}


def test_price_factors_are_trailing_only():
    """A factor that can see past as_of is a lookahead bug, not a factor."""
    profile = {"id": "px", "version": "t1", "min_families": 1,
               "family_weights": {"price": 1.0},
               "factors": ({"id": "ret_2d", "family": "price",
                            "source": "price:total_return", "window": 2,
                            "direction": "higher_is_better", "weight": 1.0,
                            "version": "t1"},)}
    data = {f"T{i:02d}": snapshot(f"T{i:02d}") for i in range(1, 13)}
    bars = {t: {"2026-09-01": 100.0, "2026-09-02": 100.0, "2026-09-03": 110.0,
                "2026-09-04": 500.0}                 # after as_of: must be unseen
            for t in data}
    rows = rows_by_ticker(analyze(data, profile=profile, bars=bars,
                                  as_of="2026-09-03"))
    # 110 / 100 - 1 = 0.10, not 500 / 100 - 1.
    assert rows["T01"]["factor_denominators"]["ret_2d"] == 12
    assert rows["T01"]["factor_percentiles"]["ret_2d"] == pytest.approx(50.0)
    assert sr._total_return([100.0, 100.0, 110.0], 2) == pytest.approx(0.10)


def test_realized_vol_needs_a_full_window():
    assert sr._realized_vol([100.0, 101.0], 5) is None
    assert sr._realized_vol([100.0, 101.0, 102.0], 2) is not None


def test_f_score_ratio_requires_enough_known_criteria():
    """2-of-2 is 100% and uninformative next to 7-of-9."""
    assert sr._f_score_ratio({"f_score": {"score": 2, "known": 2}}) is None
    assert sr._f_score_ratio({"f_score": {"score": 7, "known": 9}}) == pytest.approx(7 / 9)
    assert sr._f_score_ratio({}) is None


def test_sector_context_is_reported_separately_and_never_scored():
    data = {f"T{i:02d}": snapshot(f"T{i:02d}", fwd_pe=10 + i) for i in range(1, 13)}
    result = analyze(data)
    assert result["sector_context"]["included_in_score"] is False
    assert "sector_context" not in str(result["profile"]["factors"])


def test_excluded_by_design_fields_are_documented():
    """Currency-denominated and opinion fields must stay out, with the reason
    recorded so a later reader does not 'fix' their absence."""
    assert "balance.fcf" in sr.EXCLUDED_BY_DESIGN
    assert "market_cap" in sr.EXCLUDED_BY_DESIGN
    sources = {f["source"] for f in sr.NULL_V1_PROFILE["factors"]}
    for banned in sr.EXCLUDED_BY_DESIGN:
        assert f"fundamentals:{banned}" not in sources


# ---------------------------------------------------------------------------
# 18-19. immutability and JSON safety
# ---------------------------------------------------------------------------
def test_caller_inputs_are_never_mutated():
    data = twelve_semis()
    bars = {"T01": {"2026-09-01": 10.0, "2026-09-02": 11.0}}
    profile = copy.deepcopy(sr.NULL_V1_PROFILE)
    before = (copy.deepcopy(data), copy.deepcopy(bars), copy.deepcopy(profile))
    sr.analyze_sector_relative(data, bars, region="US", sector="Technology",
                               as_of="2026-09-06", profile=profile)
    assert (data, bars, profile) == before


def test_output_is_json_serializable_with_finite_numbers_only():
    data = twelve_semis()
    data["T13"] = snapshot("T13", fwd_pe=float("inf"), rev_yoy=float("nan"))
    encoded = json.dumps(analyze(data, profile=sr.NULL_V1_PROFILE),
                         allow_nan=False)          # raises on NaN/Infinity
    assert "NaN" not in encoded and "Infinity" not in encoded


def test_empty_input_is_handled_without_exploding():
    result = analyze({})
    assert result["candidates"] == []
    assert result["coverage"]["in_scope_names"] == 0
    assert any("no candidates matched" in w for w in result["warnings"])
    json.dumps(result, allow_nan=False)


def test_result_carries_its_own_provenance_and_disclaimer():
    result = analyze(twelve_semis())
    assert result["schema_version"] == sr.SCHEMA_VERSION
    assert result["methodology_version"] == sr.METHODOLOGY_VERSION
    assert result["as_of"] == "2026-09-06"
    assert "not wired to reports" in result["disclaimer"]
    assert result["profile"]["id"] == "value-only-test"
    assert "NOT point-in-time" in result["taxonomy"]["note"]


# ---------------------------------------------------------------------------
# 20. the kernel must stay inert
# ---------------------------------------------------------------------------
BANNED_IN_KERNEL = (
    "import os", "import time", "import datetime", "from datetime",
    "import socket", "import requests", "import urllib", "from pathlib",
    "import subprocess", "open(", "os.environ", "time.time", "datetime.now",
    "from ..llm", "from ..brokers", "from ..data", "ib_async", "openai",
    "anthropic")


def executable_code(source: str) -> str:
    """The source with comment and string tokens blanked out.

    A naive scan of raw text fails on the module's own prose: sector_relative
    carries a comment explaining why it does NOT read os.environ, and that
    comment would trip the very test it exists to justify. Blanking in place
    keeps every offset, so line numbers in a failure still mean something.
    """
    lines = source.splitlines(keepends=True)
    spans = [(tok.start, tok.end)
             for tok in tokenize.generate_tokens(io.StringIO(source).readline)
             if tok.type in (tokenize.COMMENT, tokenize.STRING)]
    for (start_row, start_col), (end_row, end_col) in reversed(spans):
        if start_row == end_row:
            line = lines[start_row - 1]
            lines[start_row - 1] = (line[:start_col]
                                    + " " * (end_col - start_col)
                                    + line[end_col:])
        else:
            lines[start_row - 1] = lines[start_row - 1][:start_col] + "\n"
            for row in range(start_row, end_row - 1):
                lines[row] = "\n"
            lines[end_row - 1] = lines[end_row - 1][end_col:]
    return "".join(lines)


def test_kernel_has_no_llm_broker_network_env_filesystem_or_clock_dependency():
    """The reproducibility guarantee is only as good as this test. `as_of` is a
    parameter precisely so nothing here reads a clock."""
    code = executable_code(inspect.getsource(sr))
    for token in BANNED_IN_KERNEL:
        assert token not in code, f"sector_relative reaches {token}"


def test_the_scan_still_catches_a_real_violation():
    """A check that cannot fail proves nothing. The blanking must hide prose
    WITHOUT hiding the same text when it is actually executable code."""
    prose_only = 'def f():\n    """explains why os.environ is avoided"""\n    return 1\n'
    guilty = "import os\n\n\ndef f():\n    return os.environ.get('X')\n"
    assert "os.environ" not in executable_code(prose_only)
    assert "os.environ" in executable_code(guilty)
    assert "import os" in executable_code(guilty)


def test_kernel_module_imports_only_math():
    tree = [line.strip() for line in inspect.getsource(sr).splitlines()
            if line.startswith(("import ", "from "))]
    assert tree == ["import math"]


# ---------------------------------------------------------------------------
# 21. the probe performs zero provider calls in offline mode
# ---------------------------------------------------------------------------
def load_probe():
    spec = importlib.util.spec_from_file_location("sector_relative_probe", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_file_exists_and_is_importable():
    assert PROBE_PATH.exists(), f"probe missing at {PROBE_PATH}"
    assert load_probe().BANNER.startswith("EXPERIMENTAL RESEARCH MEASUREMENT")


def test_probe_fixture_mode_makes_no_provider_or_broker_call(tmp_path, monkeypatch):
    probe = load_probe()
    from app.data import base as data_base

    def explode(*args, **kwargs):                      # noqa: ANN002
        raise AssertionError("offline probe attempted a provider call")

    monkeypatch.setattr(data_base, "http_get_json", explode)
    monkeypatch.setattr(data_base, "http_get_text", explode)
    monkeypatch.setenv("ALPHAMAXXIN_OFFLINE", "1")     # guard_online() tripwire

    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({
        "fundamentals": twelve_us_semis(), "bars": {}, "taxonomy": {}}))
    out = tmp_path / "artifact.json"
    assert probe.main(["--input", str(fixture), "--region", "US",
                       "--sector", "Technology", "--as-of", "2026-09-06",
                       "--out", str(out)]) == 0

    artifact = json.loads(out.read_text())
    assert artifact["input_provenance"]["provider_calls"] == 0
    assert artifact["banner"].startswith("EXPERIMENTAL RESEARCH MEASUREMENT")
    assert artifact["analysis"]["coverage"]["scored_names"] == 12
    assert artifact["security_master"]["coverage_audit"]["rows_in"] == 12


def test_probe_never_pools_names_from_another_region(tmp_path):
    """Raw multiples are not comparable across currencies and disclosure
    regimes. A US run must drop HK/SG/out-of-scope names rather than rank them
    against the S&P — and must say how many it dropped."""
    probe = load_probe()
    mixed = twelve_us_semis()
    # Deliberately best-in-class on every family, so if region filtering ever
    # regresses these three take the top ranks and the assertion below fails
    # loudly rather than the leak hiding in the middle of the table.
    for ticker in ("2020.HK", "D05.SI", "7203.T"):
        mixed[ticker] = snapshot(ticker, fwd_pe=1.0, rev_yoy=9.99, op_margin=9.99)
    fixture = tmp_path / "mixed.json"
    fixture.write_text(json.dumps({"fundamentals": mixed}))
    out = tmp_path / "artifact.json"
    assert probe.main(["--input", str(fixture), "--region", "US", "--sector",
                       "Technology", "--as-of", "2026-09-06",
                       "--out", str(out)]) == 0

    artifact = json.loads(out.read_text())
    audit = artifact["security_master"]["coverage_audit"]
    assert audit["off_region_dropped"] == 3
    assert audit["off_region_by_region"] == {"HK": 1, "SG": 1, "out_of_scope": 1}
    scored = {r["ticker"] for r in artifact["analysis"]["candidates"]}
    assert scored == set(twelve_us_semis())
    # Rank 1 is the best US name, not any of the three planted foreign ones.
    top = artifact["analysis"]["candidates"][0]
    assert top["ticker"] == "TL" and top["experimental_rank"] == 1
    assert "2020.HK" not in json.dumps(artifact["analysis"]["candidates"])


def test_probe_refuses_to_overwrite_without_force(tmp_path):
    probe = load_probe()
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"fundamentals": twelve_us_semis()}))
    out = tmp_path / "artifact.json"
    argv = ["--input", str(fixture), "--region", "US", "--sector", "Technology",
            "--as-of", "2026-09-06", "--out", str(out)]
    assert probe.main(argv) == 0
    with pytest.raises(FileExistsError):
        probe.main(argv)                                # a measurement is evidence
    assert probe.main(argv + ["--force"]) == 0


def test_probe_leaves_no_temp_file_behind(tmp_path):
    probe = load_probe()
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"fundamentals": twelve_us_semis()}))
    out = tmp_path / "artifact.json"
    probe.main(["--input", str(fixture), "--region", "US", "--sector",
                "Technology", "--as-of", "2026-09-06", "--out", str(out)])
    assert list(tmp_path.glob("*.tmp")) == []


def test_probe_only_reaches_the_broker_behind_the_explicit_flag():
    """The IBKR import is function-local, so a run without --ibkr-taxonomy
    cannot touch the broker module at all."""
    source = PROBE_PATH.read_text()
    module_level = [line for line in source.splitlines()
                    if line.startswith(("import ", "from "))]
    assert not any("ibkr" in line or "broker" in line for line in module_level)
    for banned in ("get_ibkr_positions", "get_ibkr_account_summary",
                   "placeOrder", "reqMktData", "reqScannerSubscription"):
        assert banned not in source, f"probe references {banned}"
