"""Chokepoint screener — a deterministic distillation of Serenity's
(@aleabitoreddit) "Chokepoint Theory": trace hyperscaler AI capex upstream to
the narrow supplier of a critical input, and flag when a small cap's market
value is out of scale with the demand flowing through its bottleneck.

Distilled screening rules (from her published methodology; the curated map
encodes the supply-chain research a human still has to do):
  [a] supplier concentration — the name controls a critical input (map field
      `input` + `share_note`, curated from filings/industry sources);
  [b] operational asymmetry — small market cap (< $5B) vs the bottleneck's TAM;
  [c] revenue inflection — growth running hot with analysts still upgrading
      (rev_yoy + estimate-revision delta from our fundamentals);
  [d] rotation phase — each name tagged with its sub-sector so the analyst can
      read where institutional flows are in the memory→transceiver→light-source
      sequence;
  [f] dilution/quality trap — red-line combos and heavy short interest damp
      the score (her IREN-style flip);
  [g] validation window — every flagged setup lands in the conviction ledger,
      which already measures whether calls validate in the following weeks.

This is decision support distilled from a self-reported track record — the
lens prompt is required to say so, and the backtester/ledger judge it like
every other signal.
# ponytail: curated map, revisit quarterly. TAM sizing and true supplier-share
# data are paid-data territory; `share_note` is sourced prose, not a number.
"""
from ..data.base import to_number

# Curated chokepoint universe — AI-infrastructure small/mid caps where one
# company concentrates a critical input. share_note is the human-researched
# claim to verify, not gospel.
CHOKEPOINTS = {
    "AXTI": {"input": "InP/GaAs substrates for photonics", "phase": "light_sources",
             "share_note": "leading merchant InP substrate supplier (the original 'Strait of AXTI' thesis)"},
    "SIVE": {"input": "external laser light sources for silicon photonics", "phase": "light_sources",
             "share_note": "pure-play external light source vendor for SiPh/CPO"},
    "AAOI": {"input": "optical transceivers for datacenter interconnect", "phase": "transceivers",
             "share_note": "US-listed transceiver maker with hyperscaler exposure"},
    "LITE": {"input": "optical components & transceivers", "phase": "transceivers",
             "share_note": "major optical component supplier (datacom + telecom)"},
    "COHR": {"input": "optical components, lasers, transceivers", "phase": "transceivers",
             "share_note": "scale supplier across datacom optics"},
    "FN": {"input": "optical/electronic manufacturing for networking", "phase": "transceivers",
           "share_note": "key contract manufacturer for optical modules"},
    "AEHR": {"input": "wafer-level burn-in & test for SiC/photonics", "phase": "test",
             "share_note": "near-sole supplier of wafer-level burn-in for some device classes"},
    "CAMT": {"input": "semiconductor inspection for advanced packaging", "phase": "packaging",
             "share_note": "inspection niche leader riding HBM/advanced packaging"},
    "ONTO": {"input": "process control for advanced packaging/HBM", "phase": "packaging",
             "share_note": "metrology/inspection exposure to HBM capacity buildout"},
    "MRVL": {"input": "custom AI silicon & optical DSPs", "phase": "anchor",
             "share_note": "her core large-cap anchor: custom ASIC + optical DSP chokepoints"},
}

MAX_ASYMMETRY_CAP_USD = 5e9   # rule [b]: below this, demand shifts move the stock


def score_chokepoint(ticker: str, spec: dict, fundamentals: dict | None) -> dict:
    """One name → mechanical chokepoint read. Uses only computed fundamentals;
    absent data lowers coverage, never fakes a check."""
    f = fundamentals or {}
    cap = to_number(f.get("market_cap"))
    growth = (f.get("growth") or {})
    rev_yoy = to_number(growth.get("rev_yoy"))
    trend = (f.get("analyst") or {}).get("trend") or {}
    delta = to_number(trend.get("delta_3m"))
    short_pct = to_number((f.get("short_interest") or {}).get("pct_float"))
    red_lines = bool(f.get("quality_flags")) and any(
        "combo" in fl for fl in f.get("quality_flags", []))

    checks = {
        "asymmetry_smallcap": cap is not None and cap < MAX_ASYMMETRY_CAP_USD,
        "revenue_inflection": rev_yoy is not None and rev_yoy > 0.25,
        "analysts_upgrading": delta is not None and delta > 0,
        "not_crowded_short": short_pct is None or short_pct < 0.15,
        "no_red_lines": not red_lines,
    }
    known = {k: v for k, v in checks.items()
             if not (k == "asymmetry_smallcap" and cap is None)
             and not (k == "revenue_inflection" and rev_yoy is None)
             and not (k == "analysts_upgrading" and delta is None)}
    score = round(100 * sum(known.values()) / len(known)) if known else None
    return {
        "ticker": ticker,
        "input": spec["input"],
        "phase": spec["phase"],
        "share_note": spec["share_note"],
        "market_cap": cap,
        "rev_yoy": rev_yoy,
        "estimate_delta_3m": delta,
        "short_pct_float": short_pct,
        "checks": checks,
        "checks_known": len(known),
        "score": score,
    }


def screen(yfinance, fundamentals_fn=None) -> dict:
    """Score the curated universe. fundamentals_fn(ticker) → fundamentals
    snapshot (injectable for tests); default builds it from yfinance raw via
    the fundamentals skill so all coercion/red-line logic is shared."""
    from . import fundamentals as fund_skill

    def default_fn(t):
        raw = yfinance.fundamentals(t) if yfinance.available else None
        return fund_skill.compute_fundamentals(t, raw)

    fn = fundamentals_fn or default_fn
    rows = [score_chokepoint(t, spec, fn(t)) for t, spec in CHOKEPOINTS.items()]
    scored = sorted((r for r in rows if r["score"] is not None),
                    key=lambda r: -r["score"])
    return {"candidates": scored,
            "uncovered": [r["ticker"] for r in rows if r["score"] is None],
            "universe_size": len(CHOKEPOINTS),
            "methodology": "Chokepoint Theory (distilled from @aleabitoreddit; "
                           "self-reported track record — validate via ledger)"}
