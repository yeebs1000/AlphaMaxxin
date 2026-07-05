"""Sizing suggestions — deterministic replacement for the numeric half of
the v1 Portfolio Construction / Execution agents: per-name cap enforcement,
signal-tilted target weights, ATR-based stops. The Risk analyst narrates
these; the LLM never picks numbers."""

MAX_SINGLE_NAME_WT = 0.15   # per-name cap
MIN_ACTIONABLE_DRIFT = 0.02  # ignore rebalance noise below 2 points of weight


def suggest_sizing(summary: dict, composites: dict,
                   technical_snaps: dict | None = None) -> list[dict]:
    """[{ticker, current_wt, suggested_wt, action, atr_stop, rationale}]
    summary: performance.portfolio_summary output
    composites: {ticker: signals.aggregate output}
    """
    rows = summary.get("holdings", [])
    if not rows:
        return []

    # Signal-tilted target: start from current weight, tilt toward/away by
    # composite score, clamp to the per-name cap, renormalize.
    raw_targets = {}
    for r in rows:
        ticker = r["ticker"]
        score = (composites.get(ticker) or {}).get("composite_score")
        tilt = (score / 100) * 0.05 if score is not None else 0.0  # ±5 pts max
        raw_targets[ticker] = max(0.0, min(MAX_SINGLE_NAME_WT, r["weight"] + tilt))
    total = sum(raw_targets.values())
    targets = {t: (w / total if total else 0.0) for t, w in raw_targets.items()}

    out = []
    for r in rows:
        ticker = r["ticker"]
        current, target = r["weight"], targets[ticker]
        drift = target - current
        if current > MAX_SINGLE_NAME_WT:
            action = "trim"
            rationale = f"{current:.0%} exceeds the {MAX_SINGLE_NAME_WT:.0%} single-name cap"
        elif abs(drift) < MIN_ACTIONABLE_DRIFT:
            action = "hold"
            rationale = "within target band"
        elif drift > 0:
            action = "accumulate"
            rationale = f"composite signal supports +{drift:.1%} weight"
        else:
            action = "reduce"
            rationale = f"composite signal supports {drift:.1%} weight"

        snap = (technical_snaps or {}).get(ticker) or {}
        atr14, last = snap.get("atr14"), snap.get("last_close")
        atr_stop = round(last - 2 * atr14, 2) if atr14 and last else None

        out.append({
            "ticker": ticker,
            "current_wt": round(current, 4),
            "suggested_wt": round(target, 4),
            "action": action,
            "atr_stop": atr_stop,
            "rationale": rationale,
        })
    out.sort(key=lambda x: abs(x["suggested_wt"] - x["current_wt"]), reverse=True)
    return out
