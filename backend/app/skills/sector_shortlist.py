"""Deterministic research shortlist — the LLM containment boundary.

`~/infra/SECTOR-ANALYSIS-WORK-BRIEF.md` §3.7 blocks production sector
integration until the rendering path can prove that a model cannot change what
is on the list or what order it is in. The original test — "different prose,
identical list" — is necessary but not sufficient, because a model that may
omit a name is performing selection whether or not it reorders anything.

This module is that proof. The rules it enforces:

  1. Membership and order come from `build_shortlist()` and nothing else.
  2. `render_shortlist()` iterates the canonical entries. Model text is
     decoration hung off a ticker, never a source of rows.
  3. A name the model omitted still renders. Omission cannot become selection.
  4. A name the model invented is dropped and reported. Invention cannot
     become inclusion.
  5. A model-supplied ordering is ignored and reported as a violation.
  6. Note text is sanitized so it cannot forge a table row or a heading.
  7. A fingerprint over membership+order changes when either changes and is
     stable when only prose changes.

Purity: no network, no filesystem, no clock, no environment, no LLM client.
`hashlib` is the only import beyond the standard collections — it is a pure
function of its input, which is exactly what a fingerprint has to be.

Vocabulary is deliberate. This is a "research shortlist" of "candidates for
further diligence", never a list of companies worth buying, and it carries no
action, size, target, stop or order.
"""
import hashlib

SCHEMA_VERSION = "sector_shortlist-1"

DISCLAIMER = ("EXPERIMENTAL RESEARCH MEASUREMENT — candidates for further "
              "diligence, not advice, not a signal, not an order")

# Words that would turn a research artifact into an instruction. The template
# emits none of them; a model note containing one is FLAGGED rather than
# silently stripped, because quietly editing a model's words hides the problem
# instead of surfacing it.
ACTION_LANGUAGE = ("buy", "sell", "short", "long", "position size", "allocate",
                   "stop loss", "stop-loss", "price target", "take profit",
                   "enter", "exit", "overweight", "underweight")


def _sanitize_note(text) -> str:
    """One line of plain text, safe to place in a table cell.

    A model that can emit a newline or a pipe into a markdown table can forge
    an extra row, which is membership by another route. Collapse both.
    """
    if not isinstance(text, str):
        return ""
    flattened = text.replace("|", "/").replace("\r", " ").replace("\n", " ")
    flattened = " ".join(flattened.split())
    return flattened[:280]


def scan_for_action_language(text) -> list:
    """Which action words a note contains. Reported, never auto-removed."""
    if not isinstance(text, str):
        return []
    lowered = text.lower()
    return sorted({word for word in ACTION_LANGUAGE if word in lowered})


def fingerprint(entries) -> str:
    """Stable hash of membership AND order — and of nothing else.

    Prose changes must not move it, or it cannot be used to prove that prose
    changes did not move the list.
    """
    payload = "\n".join(f"{index}:{entry['ticker']}"
                        for index, entry in enumerate(entries))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_shortlist(analysis: dict, *, limit: int = 10,
                    min_score: float | None = None) -> dict:
    """The canonical list. Derived only from the deterministic analysis.

    Candidates without an experimental score are never shortlisted — an
    unscored name is a coverage failure, and promoting it would let missing
    data look like a selection.
    """
    scored = [row for row in (analysis.get("candidates") or [])
              if row.get("experimental_score") is not None]
    if min_score is not None:
        scored = [row for row in scored if row["experimental_score"] >= min_score]
    # Re-sort here rather than trusting the caller's order: this function is
    # the definition of the order, so it must not inherit one.
    scored.sort(key=lambda row: (-row["experimental_score"], row["ticker"]))
    entries = []
    for rank, row in enumerate(scored[:limit], start=1):
        entries.append({
            "rank": rank,
            "ticker": row["ticker"],
            "sector": row.get("sector"),
            "industry": row.get("industry"),
            "experimental_score": row["experimental_score"],
            "peer_level_used": row.get("peer_level_used"),
            "peer_count": row.get("peer_count"),
            "family_scores": dict(row.get("family_scores") or {}),
        })
    scope = analysis.get("scope") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "disclaimer": DISCLAIMER,
        "as_of": analysis.get("as_of"),
        "scope": dict(scope),
        "methodology_version": analysis.get("methodology_version"),
        "profile_id": (analysis.get("profile") or {}).get("id"),
        "policy": {"limit": limit, "min_score": min_score,
                   "ordering": "experimental_score desc, ticker asc",
                   "unscored_names": "never shortlisted"},
        "entries": entries,
        "eligible_scored": len(scored),
        "fingerprint": fingerprint(entries),
    }


def reconcile_model_output(shortlist: dict, model_entries) -> dict:
    """Take a model's return value and extract ONLY note text from it.

    Everything else a model might send — its ordering, its membership, its own
    scores — is discarded here and reported as a violation. The canonical list
    is returned untouched, so a caller cannot accidentally propagate a model's
    opinion about who belongs on it.
    """
    canonical = [entry["ticker"] for entry in shortlist.get("entries") or []]
    canonical_set = set(canonical)
    notes, flagged, violations = {}, {}, []
    seen_order = []

    for item in (model_entries or []):
        if not isinstance(item, dict):
            violations.append({"type": "malformed_entry", "detail": repr(item)[:120]})
            continue
        ticker = item.get("ticker")
        if ticker not in canonical_set:
            violations.append({"type": "invented", "ticker": ticker})
            continue
        if ticker in notes:
            violations.append({"type": "duplicate", "ticker": ticker})
            continue
        seen_order.append(ticker)
        note = _sanitize_note(item.get("note") or item.get("comment") or "")
        notes[ticker] = note
        found = scan_for_action_language(note)
        if found:
            flagged[ticker] = found
        for forbidden in ("rank", "score", "experimental_score", "order",
                          "position_size", "target", "stop"):
            if item.get(forbidden) is not None:
                violations.append({"type": "model_supplied_field",
                                   "ticker": ticker, "field": forbidden})

    omitted = [t for t in canonical if t not in notes]
    for ticker in omitted:
        violations.append({"type": "omitted", "ticker": ticker})
    expected_order = [t for t in canonical if t in notes]
    if seen_order != expected_order:
        violations.append({"type": "reordered",
                           "model_order": seen_order,
                           "canonical_order": expected_order})

    return {
        "accepted": not violations,
        "violations": violations,
        "notes": notes,                      # canonical tickers only
        "action_language_flagged": flagged,
        "omitted": omitted,
        "canonical_fingerprint": shortlist.get("fingerprint"),
    }


def render_shortlist(shortlist: dict, notes_by_ticker: dict | None = None) -> str:
    """Markdown driven by the canonical entries.

    The loop is over `shortlist["entries"]`. There is no code path by which a
    model's output can add, remove or move a row — the worst it can do to this
    function is supply a note for a ticker, or fail to.
    """
    notes_by_ticker = notes_by_ticker or {}
    scope = shortlist.get("scope") or {}
    lines = [
        f"## Research shortlist — {scope.get('region', '?')} / "
        f"{scope.get('sector', '?')}",
        "",
        f"_{shortlist.get('disclaimer', DISCLAIMER)}_",
        "",
        f"As of {shortlist.get('as_of')} · profile "
        f"`{shortlist.get('profile_id')}` · method "
        f"`{shortlist.get('methodology_version')}` · list "
        f"`{(shortlist.get('fingerprint') or '')[:12]}`",
        "",
        "Candidates for further diligence, ordered by a deterministic "
        "peer-relative score. Ordering and membership are computed in Python; "
        "commentary is descriptive only.",
        "",
        "| # | Ticker | Industry | Score | Peer level | n | Notes |",
        "|--:|---|---|--:|---|--:|---|",
    ]
    for entry in shortlist.get("entries") or []:
        note = _sanitize_note(notes_by_ticker.get(entry["ticker"], ""))
        lines.append(
            f"| {entry['rank']} | {entry['ticker']} | "
            f"{entry.get('industry') or '—'} | "
            f"{entry['experimental_score']} | "
            f"{entry.get('peer_level_used') or '—'} | "
            f"{entry.get('peer_count') or 0} | {note or '—'} |")
    if not shortlist.get("entries"):
        lines.append("| — | _no candidate met the coverage bar_ | | | | | |")
    lines.extend([
        "",
        f"Scored candidates available: {shortlist.get('eligible_scored', 0)}; "
        f"shown: {len(shortlist.get('entries') or [])} "
        f"(limit {(shortlist.get('policy') or {}).get('limit')}).",
    ])
    return "\n".join(lines)
