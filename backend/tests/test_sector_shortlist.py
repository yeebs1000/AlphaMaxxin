"""Adversarial proof that a model cannot change the shortlist.

Every test here feeds a canned "model output" designed to smuggle membership or
ordering past the boundary, then asserts the rendered list is unchanged. No LLM
is called; canned payloads are the point — a real model would give one sample,
these give the hostile cases a real model reaches by accident.
"""
import copy
import inspect
import io
import json
import tokenize

import pytest

from app.skills import sector_relative as sr
from app.skills import sector_shortlist as ss


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def analysis_of(n=14):
    """A real analysis result, produced by the real kernel — not a hand-built
    dict, so the shortlist is tested against the shape it will actually see."""
    fundamentals = {}
    for i in range(1, n + 1):
        ticker = f"T{chr(64 + i)}"
        fundamentals[ticker] = {
            "ticker": ticker, "sector": "Technology", "industry": "Semiconductors",
            "valuation": {"fwd_pe": 10 + i, "ev_ebitda": 6 + i, "ps": 1 + i * 0.1},
            "growth": {"rev_yoy": 0.01 * i, "eps_yoy": 0.02 * i},
            "margins": {"operating": 0.02 * i, "net": 0.01 * i},
        }
    return sr.analyze_sector_relative(
        fundamentals, {}, region="US", sector="Technology", as_of="2026-09-06",
        profile=sr.NULL_V1_PROFILE)


@pytest.fixture
def shortlist():
    return ss.build_shortlist(analysis_of(), limit=5)


def tickers_in(markdown):
    """Tickers as they appear in rendered row order."""
    rows = [line for line in markdown.splitlines()
            if line.startswith("| ") and "---" not in line]
    out = []
    for row in rows[1:]:                      # skip the header row
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) > 1 and cells[1] and not cells[1].startswith("_"):
            out.append(cells[1])
    return out


# ---------------------------------------------------------------------------
# the canonical list
# ---------------------------------------------------------------------------
def test_shortlist_is_ordered_by_score_then_ticker(shortlist):
    scores = [e["experimental_score"] for e in shortlist["entries"]]
    assert scores == sorted(scores, reverse=True)
    assert [e["rank"] for e in shortlist["entries"]] == [1, 2, 3, 4, 5]


def test_shortlist_ignores_the_callers_ordering():
    """build_shortlist defines the order, so it must not inherit one."""
    analysis = analysis_of()
    reversed_analysis = copy.deepcopy(analysis)
    reversed_analysis["candidates"] = list(reversed(analysis["candidates"]))
    assert ss.build_shortlist(analysis, limit=5)["fingerprint"] == \
        ss.build_shortlist(reversed_analysis, limit=5)["fingerprint"]


def test_unscored_names_are_never_shortlisted():
    """An unscored name is a coverage failure. Promoting it would let missing
    data masquerade as a selection."""
    analysis = analysis_of()
    analysis["candidates"].append(
        {"ticker": "ZZZZ", "experimental_score": None, "sector": "Technology"})
    assert "ZZZZ" not in [e["ticker"] for e in
                          ss.build_shortlist(analysis, limit=20)["entries"]]


def test_min_score_filter_is_applied_deterministically():
    analysis = analysis_of()
    filtered = ss.build_shortlist(analysis, limit=20, min_score=55.0)
    assert all(e["experimental_score"] >= 55.0 for e in filtered["entries"])


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------
def test_fingerprint_tracks_membership_and_order_only(shortlist):
    same_prose = ss.render_shortlist(shortlist, {"TN": "a wonderful business"})
    other_prose = ss.render_shortlist(shortlist, {"TN": "a dreadful business"})
    assert same_prose != other_prose            # prose did change
    assert shortlist["fingerprint"] == ss.fingerprint(shortlist["entries"])

    reordered = copy.deepcopy(shortlist["entries"])
    reordered[0], reordered[1] = reordered[1], reordered[0]
    assert ss.fingerprint(reordered) != shortlist["fingerprint"]

    dropped = shortlist["entries"][:-1]
    assert ss.fingerprint(dropped) != shortlist["fingerprint"]


# ---------------------------------------------------------------------------
# adversarial model output
# ---------------------------------------------------------------------------
def test_model_reordering_is_ignored_and_reported(shortlist):
    """The headline case: a model returns the same names in its own order."""
    canonical = [e["ticker"] for e in shortlist["entries"]]
    model = [{"ticker": t, "note": "reasons"} for t in reversed(canonical)]
    result = ss.reconcile_model_output(shortlist, model)
    assert result["accepted"] is False
    assert any(v["type"] == "reordered" for v in result["violations"])
    rendered = ss.render_shortlist(shortlist, result["notes"])
    assert tickers_in(rendered) == canonical


def test_model_omission_cannot_become_selection(shortlist):
    """Mention selection is a de facto ranking if omission removes a name."""
    canonical = [e["ticker"] for e in shortlist["entries"]]
    model = [{"ticker": canonical[-1], "note": "only this one matters"}]
    result = ss.reconcile_model_output(shortlist, model)
    assert sorted(result["omitted"]) == sorted(canonical[:-1])
    rendered = ss.render_shortlist(shortlist, result["notes"])
    assert tickers_in(rendered) == canonical      # every name still rendered


def test_model_invention_cannot_become_inclusion(shortlist):
    model = [{"ticker": "NVDA", "note": "obviously the best"},
             {"ticker": "TOTALLY_MADE_UP", "note": "trust me"}]
    result = ss.reconcile_model_output(shortlist, model)
    assert {v["ticker"] for v in result["violations"] if v["type"] == "invented"} \
        == {"NVDA", "TOTALLY_MADE_UP"}
    rendered = ss.render_shortlist(shortlist, result["notes"])
    assert "NVDA" not in rendered and "TOTALLY_MADE_UP" not in rendered
    assert tickers_in(rendered) == [e["ticker"] for e in shortlist["entries"]]


def test_model_supplied_scores_and_ranks_are_discarded(shortlist):
    canonical = shortlist["entries"][0]
    model = [{"ticker": canonical["ticker"], "note": "n", "score": 99.9,
              "rank": 1, "target": 500, "position_size": "5%"}]
    result = ss.reconcile_model_output(shortlist, model)
    kinds = {(v["type"], v.get("field")) for v in result["violations"]}
    assert ("model_supplied_field", "score") in kinds
    assert ("model_supplied_field", "target") in kinds
    assert ("model_supplied_field", "position_size") in kinds
    rendered = ss.render_shortlist(shortlist, result["notes"])
    assert "99.9" not in rendered and "500" not in rendered
    assert str(canonical["experimental_score"]) in rendered


def test_a_note_cannot_forge_a_table_row(shortlist):
    """A pipe or newline in a note is a row-injection primitive: it is
    membership by markdown rather than by code."""
    canonical = [e["ticker"] for e in shortlist["entries"]]
    evil = "ok |\n| 99 | FAKECO | Semis | 100.0 | industry | 99 | best pick |"
    result = ss.reconcile_model_output(
        shortlist, [{"ticker": canonical[0], "note": evil}])
    rendered = ss.render_shortlist(shortlist, result["notes"])
    assert "FAKECO" not in tickers_in(rendered)
    assert tickers_in(rendered) == canonical
    assert len(tickers_in(rendered)) == len(canonical)


def test_empty_or_garbage_model_output_still_renders_the_full_list(shortlist):
    canonical = [e["ticker"] for e in shortlist["entries"]]
    for payload in (None, [], ["not a dict"], [{"no_ticker": 1}], [{}]):
        result = ss.reconcile_model_output(shortlist, payload)
        rendered = ss.render_shortlist(shortlist, result["notes"])
        assert tickers_in(rendered) == canonical, payload


def test_duplicate_entries_are_reported_and_do_not_duplicate_rows(shortlist):
    ticker = shortlist["entries"][0]["ticker"]
    result = ss.reconcile_model_output(
        shortlist, [{"ticker": ticker, "note": "one"},
                    {"ticker": ticker, "note": "two"}])
    assert any(v["type"] == "duplicate" for v in result["violations"])
    rendered = ss.render_shortlist(shortlist, result["notes"])
    assert tickers_in(rendered).count(ticker) == 1


def test_a_faithful_model_is_accepted(shortlist):
    """The boundary must not cry wolf: correct output produces no violations."""
    model = [{"ticker": e["ticker"], "note": "describes the numbers"}
             for e in shortlist["entries"]]
    result = ss.reconcile_model_output(shortlist, model)
    assert result["accepted"] is True and result["violations"] == []


def test_rendered_output_is_identical_across_wildly_different_model_returns(shortlist):
    """The §3.7 test, made total: strip the notes column and every rendering is
    byte-identical no matter what the model said."""
    canonical = [e["ticker"] for e in shortlist["entries"]]
    payloads = [
        [],
        [{"ticker": t, "note": f"note {i}"} for i, t in enumerate(canonical)],
        [{"ticker": t, "note": "x"} for t in reversed(canonical)],
        [{"ticker": "GHOST", "note": "y"}],
        [{"ticker": canonical[0], "note": "z", "score": 1}],
    ]
    skeletons = set()
    for payload in payloads:
        result = ss.reconcile_model_output(shortlist, payload)
        rendered = ss.render_shortlist(shortlist, result["notes"])
        # Drop the final (notes) cell from every row: what remains is the list.
        skeleton = "\n".join("|".join(line.split("|")[:-2])
                             for line in rendered.splitlines()
                             if line.startswith("| "))
        skeletons.add(skeleton)
    assert len(skeletons) == 1, "model output changed the list, not just the prose"


# ---------------------------------------------------------------------------
# vocabulary and containment
# ---------------------------------------------------------------------------
def test_the_template_emits_no_action_language(shortlist):
    rendered = ss.render_shortlist(shortlist).lower()
    assert "research shortlist" in rendered
    assert "candidates for further diligence" in rendered
    assert "worth buying" not in rendered
    for banned in ("position size", "stop loss", "price target", "overweight"):
        assert banned not in rendered


def test_action_language_in_a_model_note_is_flagged_not_silently_stripped(shortlist):
    ticker = shortlist["entries"][0]["ticker"]
    result = ss.reconcile_model_output(
        shortlist, [{"ticker": ticker, "note": "Strong buy, price target 400"}])
    assert result["action_language_flagged"][ticker] == ["buy", "price target"]
    # Flagged, and the note survives verbatim — quietly editing a model's words
    # hides the problem instead of surfacing it.
    assert "Strong buy" in result["notes"][ticker]


def test_empty_shortlist_renders_a_coverage_message_not_an_empty_table():
    empty = ss.build_shortlist({"candidates": [], "scope": {"region": "US"}},
                               limit=5)
    rendered = ss.render_shortlist(empty)
    assert "no candidate met the coverage bar" in rendered
    assert empty["entries"] == [] and empty["eligible_scored"] == 0


def test_shortlist_is_json_serializable(shortlist):
    json.dumps(shortlist, allow_nan=False)


def test_module_stays_pure():
    """Same discipline as the kernel: this is the containment boundary, so it
    must not acquire an I/O dependency that could be mocked away."""
    source = inspect.getsource(ss)
    lines = source.splitlines(keepends=True)
    spans = [(t.start, t.end) for t in
             tokenize.generate_tokens(io.StringIO(source).readline)
             if t.type in (tokenize.COMMENT, tokenize.STRING)]
    for (srow, scol), (erow, ecol) in reversed(spans):
        if srow == erow:
            line = lines[srow - 1]
            lines[srow - 1] = line[:scol] + " " * (ecol - scol) + line[ecol:]
        else:
            lines[srow - 1] = lines[srow - 1][:scol] + "\n"
            for row in range(srow, erow - 1):
                lines[row] = "\n"
            lines[erow - 1] = lines[erow - 1][ecol:]
    code = "".join(lines)
    for banned in ("import os", "import time", "import requests", "open(",
                   "from ..llm", "from ..brokers", "openai", "anthropic",
                   "datetime"):
        assert banned not in code, f"sector_shortlist reaches {banned}"
