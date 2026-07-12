"""Sizing suggestions — deterministic replacement for the numeric half of
the v1 Portfolio Construction / Execution agents: per-name cap enforcement,
signal-tilted target weights, ATR-based stops, and a covariance-aware
minimum-variance tilt. The Risk analyst narrates these; the LLM never picks
numbers."""

MAX_SINGLE_NAME_WT = 0.15   # per-name cap
MIN_ACTIONABLE_DRIFT = 0.02  # ignore rebalance noise below 2 points of weight


def min_variance_tilt(weights: dict, returns: dict, cap: float = 0.20,
                      min_bars: int = 60) -> dict | None:
    """Long-only minimum-variance weights from a Ledoit-Wolf shrunk
    covariance of the holdings' daily returns — the covariance-aware second
    opinion next to suggest_sizing's signal tilts. Needs no return forecasts
    (max-Sharpe would; forecasts are where optimizers go to lie).

    # ponytail: clip-and-renormalize is a heuristic projection, not a QP
    # solver — good enough for a tilt suggestion; use cvxpy if exact
    # constrained optimization ever matters.
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
    n_bars = min(len(returns[t]) for t in tickers)
    X = np.array([np.asarray(returns[t], dtype=float)[-n_bars:]
                  for t in tickers]).T  # (samples, assets)
    cov = LedoitWolf().fit(X).covariance_
    try:
        inv = np.linalg.pinv(cov)
    except np.linalg.LinAlgError:
        return None
    w = np.clip(inv @ np.ones(len(tickers)), 0.0, None)
    if w.sum() <= 0 or cap * len(tickers) < 1.0:
        return None
    w = w / w.sum()
    for _ in range(len(tickers)):  # waterfall: pin over-cap names, spread the rest
        over = w > cap + 1e-12
        if not over.any():
            break
        free = 1.0 - cap * over.sum()
        rest = w[~over].sum()
        w[over] = cap
        w[~over] = w[~over] * (free / rest) if rest > 0 else free / (~over).sum()
    suggested = {t: round(float(x), 4) for t, x in zip(tickers, w)}
    shifts = sorted(
        ({"ticker": t, "current_wt": round(weights[t], 4),
          "suggested_wt": suggested[t],
          "delta": round(suggested[t] - weights[t], 4)} for t in tickers),
        key=lambda s: -abs(s["delta"]))
    material = [s for s in shifts if abs(s["delta"]) >= MIN_ACTIONABLE_DRIFT]
    return {
        "method": f"Ledoit-Wolf min-variance, long-only, {cap:.0%} cap, "
                  f"{n_bars} daily bars",
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
