"""Portfolio health — a PM-grade assessment of the whole book.

The existing risk skill answers "what are my exposures". This answers the
question a portfolio manager actually gets asked: **is this book well built,
and what should I do about it?** It scores six dimensions, grades the whole,
and emits typed, numeric, actionable recommendations.

DETERMINISTIC by construction. Every score is a documented function of
computed inputs — no LLM decides anything here, and nothing is predictive.
The recommendations are portfolio-construction rules (concentration caps,
sleeve targets, sector gaps, correlation clusters), not forecasts: this says
"single name at 27% breaches a 20% cap", never "this stock will fall".

Scores are 0-100 where 100 = no issues found on that dimension. They measure
STRUCTURE, not skill — a perfectly built book can still lose money.
"""
import math

# --- policy constants. A real mandate writes these down; so do we, in one
# place, so the reader can see exactly what the book is being judged against.
MAX_SINGLE_NAME = 0.20        # any one position
MAX_SECTOR = 0.30             # any one sector
MAX_TOP5 = 0.60               # top five combined
MIN_EFFECTIVE_N = 8.0         # 1/HHI — "how many positions do I really own"
BETA_TARGET = (0.70, 1.05)    # the mandate is "minimise beta" -> aim at/below 1
MAX_CLUSTER = 0.35            # combined weight of a highly-correlated cluster
CLUSTER_CORR = 0.70
MAX_UNCLASSIFIED = 0.25       # sector-unknown share before it clouds the read

# Sleeve mix targets (business_stage assigns the sleeve).
SLEEVE_TARGETS = {
    "core":        (0.45, 0.75),
    "ballast":     (0.10, 0.35),
    "tactical":    (0.00, 0.25),
    "speculative": (0.00, 0.10),
}
DEFENSIVE_SECTORS = ("Consumer Defensive", "Healthcare", "Utilities")
MIN_DEFENSIVE = 0.15

_GRADES = ((85, "A"), (70, "B"), (55, "C"), (40, "D"))


def _grade(score):
    for cutoff, letter in _GRADES:
        if score >= cutoff:
            return letter
    return "F"


def _band_score(value, lo, hi, tolerance):
    """100 inside [lo, hi], decaying linearly to 0 `tolerance` beyond it."""
    if value is None:
        return None
    if lo <= value <= hi:
        return 100.0
    gap = (lo - value) if value < lo else (value - hi)
    return max(0.0, 100.0 * (1 - gap / tolerance))


def _cap_score(value, cap, tolerance):
    """100 at or under the cap, decaying to 0 at cap+tolerance."""
    if value is None:
        return None
    if value <= cap:
        return 100.0
    return max(0.0, 100.0 * (1 - (value - cap) / tolerance))


def _weights_by(positions, key):
    out = {}
    for p in positions:
        k = p.get(key) or "Unclassified"
        out[k] = out.get(k, 0.0) + (p.get("weight") or 0.0)
    return out


def _correlated_clusters(positions, corr):
    """Greedy grouping of names correlating >= CLUSTER_CORR. Surfaces hidden
    concentration: five names in five 'different' sectors that all trade as
    one AI-infrastructure bet is a single position wearing a disguise."""
    tickers = [p["ticker"] for p in positions]
    weight = {p["ticker"]: p.get("weight") or 0.0 for p in positions}
    seen, clusters = set(), []
    for t in tickers:
        if t in seen:
            continue
        group = [t]
        for u in tickers:
            if u == t or u in seen:
                continue
            c = (corr.get((t, u)) if corr else None)
            if c is None and corr:
                c = corr.get((u, t))
            if c is not None and c >= CLUSTER_CORR:
                group.append(u)
        if len(group) > 1:
            seen.update(group)
            clusters.append({"tickers": group,
                             "weight": round(sum(weight.get(g, 0) for g in group), 4)})
    return sorted(clusters, key=lambda c: -c["weight"])


def health_report(positions: list[dict], equity_metrics: dict | None = None,
                  portfolio_beta: float | None = None,
                  corr: dict | None = None,
                  benchmark_return_pct: float | None = None) -> dict:
    """positions: [{ticker, weight, sector, sleeve, stage, fund_score, beta}].
    corr: {(a, b): correlation}. Every dimension degrades to None when its
    inputs are missing — an unscored dimension drops out of the composite
    rather than counting as a failure."""
    if not positions:
        return {"score": None, "grade": None, "dimensions": {},
                "recommendations": [], "note": "no positions"}

    total_w = sum(p.get("weight") or 0.0 for p in positions) or 1.0
    weights = {p["ticker"]: (p.get("weight") or 0.0) / total_w for p in positions}
    sectors = _weights_by(positions, "sector")
    sleeves = _weights_by(positions, "sleeve")
    recs, dims = [], {}

    # ---------------------------------------------------------------- 1. concentration
    top_name, top_w = max(weights.items(), key=lambda kv: kv[1])
    hhi = sum(w * w for w in weights.values())
    eff_n = 1.0 / hhi if hhi else 0.0
    top5 = sum(sorted(weights.values(), reverse=True)[:5])
    conc = min(_cap_score(top_w, MAX_SINGLE_NAME, 0.20),
               _cap_score(top5, MAX_TOP5, 0.25),
               _band_score(eff_n, MIN_EFFECTIVE_N, 100, MIN_EFFECTIVE_N))
    dims["concentration"] = {
        "score": round(conc, 1),
        "top_position": {"ticker": top_name, "weight": round(top_w, 4)},
        "effective_positions": round(eff_n, 1),
        "top5_weight": round(top5, 4),
        "detail": (f"largest position {top_w:.0%} ({top_name}); "
                   f"{eff_n:.1f} effective positions out of {len(positions)}"),
    }
    if top_w > MAX_SINGLE_NAME:
        recs.append({
            "priority": "high", "action": "trim", "target": top_name,
            "from": round(top_w, 4), "to": MAX_SINGLE_NAME,
            "why": (f"{top_name} is {top_w:.0%} of the book against a "
                    f"{MAX_SINGLE_NAME:.0%} single-name cap — one company "
                    "drives the result")})
    if eff_n < MIN_EFFECTIVE_N:
        recs.append({
            "priority": "medium", "action": "diversify", "target": None,
            "why": (f"only {eff_n:.1f} effective positions — the book behaves "
                    f"like {math.floor(eff_n)} holdings regardless of the "
                    f"{len(positions)} lines on the statement")})

    # ---------------------------------------------------------------- 2. sector balance
    unclassified = sectors.get("Unclassified", 0.0)
    known = {k: v for k, v in sectors.items() if k != "Unclassified"}
    max_sector, max_sector_w = (max(known.items(), key=lambda kv: kv[1])
                                if known else (None, 0.0))
    defensive = sum(v for k, v in known.items() if k in DEFENSIVE_SECTORS)
    sec_score = min(_cap_score(max_sector_w, MAX_SECTOR, 0.30),
                    _cap_score(unclassified, MAX_UNCLASSIFIED, 0.40))
    dims["sector_balance"] = {
        "score": round(sec_score, 1),
        "weights": {k: round(v, 4) for k, v in
                    sorted(sectors.items(), key=lambda kv: -kv[1])},
        "largest": {"sector": max_sector, "weight": round(max_sector_w, 4)},
        "defensive_weight": round(defensive, 4),
        "unclassified_weight": round(unclassified, 4),
        "detail": (f"largest sector {max_sector} at {max_sector_w:.0%}; "
                   f"defensive (staples/health/utilities) {defensive:.0%}"),
    }
    if max_sector and max_sector_w > MAX_SECTOR:
        recs.append({
            "priority": "high", "action": "reduce_sector", "target": max_sector,
            "from": round(max_sector_w, 4), "to": MAX_SECTOR,
            "why": (f"{max_sector} is {max_sector_w:.0%} against a "
                    f"{MAX_SECTOR:.0%} cap — a sector shock hits "
                    f"{max_sector_w:.0%} of the book at once")})
    absent = [s for s in DEFENSIVE_SECTORS if known.get(s, 0.0) < 0.02]
    if defensive < MIN_DEFENSIVE:
        gap = MIN_DEFENSIVE - defensive
        # Name the LIGHTEST sectors, not all three — listing sectors the book
        # already holds reads as "you have none of these", which is false.
        lightest = sorted(DEFENSIVE_SECTORS, key=lambda s: known.get(s, 0.0))[:2]
        recs.append({
            "priority": "medium" if gap > 0.05 else "low",
            "action": "add_defensive", "target": absent or lightest,
            "from": round(defensive, 4), "to": MIN_DEFENSIVE,
            "why": (f"defensive sectors are {defensive:.0%} of the book "
                    f"against a {MIN_DEFENSIVE:.0%} floor"
                    + (f" — none held in: {', '.join(absent)}" if absent
                       else f" — lightest: {', '.join(lightest)}"))})
    if unclassified > MAX_UNCLASSIFIED:
        recs.append({
            "priority": "low", "action": "classify",
            "target": None, "from": round(unclassified, 4),
            "why": (f"{unclassified:.0%} of the book has no sector (usually "
                    "ETFs) — sector limits cannot see it")})

    # ---------------------------------------------------------------- 3. sleeve discipline
    if any(p.get("sleeve") for p in positions):
        sleeve_scores, drifts = [], []
        for sleeve, (lo, hi) in SLEEVE_TARGETS.items():
            w = sleeves.get(sleeve, 0.0)
            sleeve_scores.append(_band_score(w, lo, hi, 0.20))
            if w > hi:
                drifts.append((sleeve, w, hi, "over"))
            elif w < lo:
                drifts.append((sleeve, w, lo, "under"))
        dims["sleeve_discipline"] = {
            "score": round(sum(sleeve_scores) / len(sleeve_scores), 1),
            "weights": {k: round(sleeves.get(k, 0.0), 4) for k in SLEEVE_TARGETS},
            "targets": {k: list(v) for k, v in SLEEVE_TARGETS.items()},
            "detail": "; ".join(f"{s} {sleeves.get(s, 0.0):.0%}"
                                for s in SLEEVE_TARGETS),
        }
        for sleeve, w, bound, direction in drifts:
            recs.append({
                "priority": "high" if sleeve == "speculative" and direction == "over"
                            else "medium",
                "action": f"{'reduce' if direction == 'over' else 'increase'}_sleeve",
                "target": sleeve, "from": round(w, 4), "to": bound,
                "why": (f"{sleeve} sleeve is {w:.0%}, {direction} the "
                        f"{bound:.0%} {'ceiling' if direction == 'over' else 'floor'}")})

    # ---------------------------------------------------------------- 4. risk posture
    lo, hi = BETA_TARGET
    beta_score = _band_score(portfolio_beta, lo, hi, 0.50)
    dd = (equity_metrics or {}).get("max_drawdown_pct")
    dims["risk_posture"] = {
        "score": round(beta_score, 1) if beta_score is not None else None,
        "portfolio_beta": portfolio_beta, "beta_target": list(BETA_TARGET),
        "max_drawdown_pct": dd,
        "detail": (f"portfolio beta {portfolio_beta} vs target {lo}-{hi}"
                   if portfolio_beta is not None else "beta unavailable"),
    }
    if portfolio_beta is not None and portfolio_beta > hi:
        recs.append({
            "priority": "medium", "action": "reduce_beta", "target": None,
            "from": portfolio_beta, "to": hi,
            "why": (f"portfolio beta {portfolio_beta} exceeds the {hi} ceiling "
                    "— the book amplifies the market rather than diversifying it")})

    # ---------------------------------------------------------------- 5. holding quality
    scored = [(p["ticker"], p.get("weight") or 0.0, p.get("fund_score"))
              for p in positions if p.get("fund_score") is not None]
    if scored:
        wsum = sum(w for _, w, _ in scored) or 1.0
        wq = sum(w * s for _, w, s in scored) / wsum
        weak = [t for t, _, s in scored if s < 50]
        dims["quality"] = {
            "score": round(wq, 1),
            "coverage": round(wsum / total_w, 2),
            "weak_holdings": weak,
            "detail": (f"weighted fundamental score {wq:.0f}/100 across "
                       f"{wsum / total_w:.0%} of the book"),
        }
        for t, w, s in scored:
            if s < 40 and w >= 0.05:
                recs.append({
                    "priority": "high", "action": "review_holding", "target": t,
                    "from": round(w, 4), "to": None,
                    "why": (f"{t} scores {s}/100 on fundamentals yet is "
                            f"{w:.0%} of the book")})

    # ---------------------------------------------------------------- 6. true diversification
    clusters = _correlated_clusters(positions, corr) if corr else []
    if corr:
        worst = clusters[0]["weight"] if clusters else 0.0
        dims["correlation"] = {
            "score": round(_cap_score(worst, MAX_CLUSTER, 0.35), 1),
            "clusters": clusters[:3],
            "detail": (f"largest correlated cluster {worst:.0%} of the book"
                       if clusters else "no highly-correlated cluster found"),
        }
        if worst > MAX_CLUSTER:
            names = ", ".join(clusters[0]["tickers"][:5])
            recs.append({
                "priority": "high", "action": "break_cluster",
                "target": clusters[0]["tickers"], "from": round(worst, 4),
                "to": MAX_CLUSTER,
                "why": (f"{worst:.0%} of the book moves together ({names}) — "
                        "these are one bet wearing several tickers")})

    # ---------------------------------------------------------------- composite
    got = [d["score"] for d in dims.values() if d.get("score") is not None]
    score = round(sum(got) / len(got), 1) if got else None
    order = {"high": 0, "medium": 1, "low": 2}
    recs.sort(key=lambda r: order.get(r["priority"], 3))
    return {
        "score": score,
        "grade": _grade(score) if score is not None else None,
        "dimensions": dims,
        "recommendations": recs,
        "performance": {
            "twr_pct": (equity_metrics or {}).get("twr_pct"),
            "benchmark_pct": benchmark_return_pct,
            "excess_pct": (round((equity_metrics or {}).get("twr_pct", 0)
                                 - benchmark_return_pct, 2)
                           if equity_metrics and equity_metrics.get("twr_pct") is not None
                           and benchmark_return_pct is not None else None),
            "sharpe_ann": (equity_metrics or {}).get("sharpe_ann"),
            "max_drawdown_pct": (equity_metrics or {}).get("max_drawdown_pct"),
            "n_snapshots": (equity_metrics or {}).get("n_snapshots"),
        },
        "note": ("structural assessment of how the book is BUILT — not a "
                 "forecast and not advice"),
    }
