"""Sizing suggestions — deterministic replacement for the numeric half of
the v1 Portfolio Construction / Execution agents: per-name cap enforcement,
signal-tilted target weights, ATR-based stops, and a covariance-aware
minimum-variance tilt. The Risk analyst narrates these; the LLM never picks
numbers."""

MAX_SINGLE_NAME_WT = 0.15   # per-name cap
MIN_ACTIONABLE_DRIFT = 0.02  # ignore rebalance noise below 2 points of weight


def _capped_weights(raw: dict, cap: float) -> tuple[dict, float]:
    """Proportional redistribution with pinned caps and explicit unused cash."""
    if not 0 < cap <= 1:
        raise ValueError("weight cap must be in (0, 1]")
    targets = dict.fromkeys(raw, 0.0)
    if sum(raw.values()) <= 0:
        return targets, 1.0
    remaining, free = 1.0, list(raw)
    while free:
        total = sum(raw[t] for t in free)
        proposed = {t: remaining * raw[t] / total if total > 0 else remaining / len(free)
                    for t in free}
        over = [t for t in free if proposed[t] > cap]
        if not over:
            targets.update(proposed)
            remaining = 0.0
            break
        for t in over:
            targets[t] = cap
            remaining = max(0.0, remaining - cap)
            free.remove(t)
    return targets, max(0.0, remaining)


def min_variance_tilt(weights: dict, returns: dict, cap: float = 0.20,
                      min_bars: int = 60) -> dict | None:
    """Long-only minimum-variance weights from a Ledoit-Wolf shrunk
    covariance of the holdings' common-interval returns — the covariance-aware second
    opinion next to suggest_sizing's signal tilts. Needs no return forecasts
    (max-Sharpe would; forecasts are where optimizers go to lie).

    # ponytail: inverse-covariance tilt with capped proportional redistribution,
    # not an exact constrained minimum-variance solution; use a QP solver if needed.
    """
    try:
        import numpy as np
        from sklearn.covariance import LedoitWolf
    except ImportError:
        return None
    tickers = [t for t, r in returns.items()
               if t in weights and len(r) >= min_bars]
    if len(tickers) < 3:
        return None
    lengths = {len(returns[t]) for t in tickers}
    if len(lengths) != 1:
        return None  # callers must supply common-date intervals, never tail alignment
    n_bars = lengths.pop()
    X = np.array([np.asarray(returns[t], dtype=float)
                  for t in tickers]).T  # (samples, assets)
    if not np.isfinite(X).all():
        return None
    cov = LedoitWolf().fit(X).covariance_
    try:
        inv = np.linalg.pinv(cov)
    except np.linalg.LinAlgError:
        return None
    w = np.clip(inv @ np.ones(len(tickers)), 0.0, None)
    if w.sum() <= 0 or cap * len(tickers) < 1.0:
        return None
    targets, _ = _capped_weights(dict(zip(tickers, w)), cap)
    suggested = {t: min(cap, round(float(x), 4)) for t, x in targets.items()}
    shifts = sorted(
        ({"ticker": t, "current_wt": round(weights[t], 4),
          "suggested_wt": suggested[t],
          "delta": round(suggested[t] - weights[t], 4)} for t in tickers),
        key=lambda s: -abs(s["delta"]))
    material = [s for s in shifts if abs(s["delta"]) >= MIN_ACTIONABLE_DRIFT]
    return {
        "method": f"Ledoit-Wolf covariance tilt, long-only, {cap:.0%} cap, "
                  f"{n_bars} common close intervals",
        "suggested_weights": suggested,
        "biggest_shifts": material[:8],
        "covered": len(tickers),
    }


def suggest_sizing(summary: dict, composites: dict,
                   technical_snaps: dict | None = None) -> list[dict]:
    """[{ticker, current_wt, suggested_wt, action, atr_stop, rationale}]
    summary: performance.portfolio_summary output
    composites: {ticker: signals.aggregate output}
    """
    if summary.get("errors"):
        return []
    rows = summary.get("holdings", [])
    if not rows:
        return []

    # Signal-tilted target: start from current weight, tilt toward/away by
    # composite score, redistribute while keeping final caps pinned.
    raw_targets = {}
    for r in rows:
        ticker = r["ticker"]
        score = (composites.get(ticker) or {}).get("composite_score")
        tilt = (score / 100) * 0.05 if score is not None else 0.0  # ±5 pts max
        raw_targets[ticker] = max(0.0, r["weight"] + tilt)
    targets, cash = _capped_weights(raw_targets, MAX_SINGLE_NAME_WT)

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
            "cash_remainder_wt": round(cash, 4),
            "action": action,
            "atr_stop": atr_stop,
            "rationale": rationale,
        })
    out.sort(key=lambda x: abs(x["suggested_wt"] - x["current_wt"]), reverse=True)
    return out
