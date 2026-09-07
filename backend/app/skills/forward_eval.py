"""Prospective forward evaluation — pre-registered protocol and its metrics.

This module answers the only question that matters and that nothing built so
far can answer: **does the sector-relative score predict anything?**

It cannot be answered today. The box has no point-in-time fundamentals and no
point-in-time sector membership, so a historical backtest would be scored with
today's labels on today's survivors — the same three biases that inflated the
existing sector-tilt simulator, all pushing the same way. The honest route is
forward: snapshot the ranking as of a date, wait, then measure.

**The protocol below is pre-registered.** It is frozen in code with a hash, and
`test_forward_eval.py` asserts the hash still matches. Changing a horizon, a
bucket count, a cost assumption or the primary metric therefore requires
editing the hash in the same commit, where a reviewer can see it. That is the
whole mechanism: it makes "we tuned it after seeing the result" visible instead
of invisible.

Purity: `math` only. No network, no filesystem, no clock — `as_of` and every
price series arrive as arguments, which is what makes an evaluation
reproducible from its own snapshot.
"""
import hashlib
import json
import math

SCHEMA_VERSION = "forward_eval-1"

# ---------------------------------------------------------------------------
# THE PRE-REGISTERED PROTOCOL — do not edit without updating PROTOCOL_HASH
# ---------------------------------------------------------------------------
PROTOCOL = {
    "protocol_version": "prereg-1",
    "registered_on": "2026-09-07",
    "amendments": [
        "2026-09-07: snapshot_cadence reworded to match the Sunday 08:30 "
        "schedule (as_of = last completed session). Made BEFORE any snapshot "
        "was evaluated — one snapshot existed and was retaken. No metric, "
        "horizon, bucket, cost or failure criterion was touched."
    ],
    "question": (
        "Does the null-v1 sector-relative experimental_score rank-predict "
        "forward total return within its own peer pool?"
    ),
    # ONE primary metric. Everything else is secondary and must be reported as
    # exploratory — with 3 regions x 4 families x 2 horizons there are dozens
    # of ways to find a result that is not there.
    "primary_metric": "spearman_ic_20d",
    "primary_definition": (
        "Spearman rank correlation between experimental_score at as_of and "
        "20-trading-day forward total return, computed WITHIN each peer pool, "
        "then averaged across pools weighted by pool size."
    ),
    "horizons_trading_days": [20, 60],
    "secondary_metrics": [
        "spearman_ic_60d",
        "top_minus_bottom_quintile_20d",
        "top_minus_bottom_quintile_60d",
        "turnover_between_snapshots",
        "hit_rate_positive_ic",
    ],
    "buckets": 5,
    "min_names_per_pool": 12,          # same MIN_PEERS as the ranking itself
    "min_snapshots_before_reporting": 12,
    "snapshot_cadence": (
        "weekly; the job runs Sunday 08:30 SGT with every market closed, and "
        "as_of is the last completed trading session (normally Friday's "
        "close). Spacing is therefore 5 trading days."
    ),
    "rebalance": "at each snapshot; no intra-period changes",
    "universe": "US/HK/SG research universe as defined by security_master",
    "exclusions": [
        "names with no experimental_score at as_of",
        "names with no price at as_of",
        "names with no price at as_of + horizon (delisted/halted mid-window)",
        "pools below min_names_per_pool at as_of",
    ],
    # Applied to the long-short spread only; the IC is a correlation and is
    # cost-free by construction.
    "cost_ladder_bps": [0, 10, 25, 50, 85],
    "cost_note": (
        "85bps is the breakeven the existing sector-tilt simulator measured; "
        "it is included so this evaluation is comparable to that one."
    ),
    "overlap_handling": (
        "Snapshots are weekly and horizons are 20/60 trading days, so windows "
        "overlap. Effective sample size is reported as n_snapshots divided by "
        "the overlap factor (horizon / spacing), and no significance claim may "
        "be made on the raw count."
    ),
    "failure_criteria": (
        "If mean primary IC is within +/-0.02 of zero after 12 snapshots, the "
        "null-v1 profile is not predictive and the tier/profile work does not "
        "proceed to any production path on the strength of it."
    ),
    "not_claimed": [
        "no historical backtest is implied or permitted by this protocol",
        "no result here is investment advice or a trading signal",
        "current classifications are NOT point-in-time",
    ],
}


def protocol_hash(protocol: dict | None = None) -> str:
    """Stable hash of the frozen protocol. A test pins it, so any edit to the
    rules shows up as a hash change in the same diff."""
    payload = json.dumps(protocol or PROTOCOL, sort_keys=True,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Pinned. If this fails after an intentional protocol change, update it in the
# SAME commit and say why in the message.
PROTOCOL_HASH = "f44b187ff107987424edac5df669b9edb849f17ec50ac27c14f3a2b1796aa72a"


# ---------------------------------------------------------------------------
# numerics
# ---------------------------------------------------------------------------
def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _ranks(values) -> list:
    """Average ranks, ties shared — the same midrank convention the scorer uses."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        stop = index
        while stop + 1 < len(order) and values[order[stop + 1]] == values[order[index]]:
            stop += 1
        midrank = (index + stop) / 2 + 1
        for position in range(index, stop + 1):
            ranks[order[position]] = midrank
        index = stop + 1
    return ranks


def spearman(xs, ys):
    """Spearman rank correlation, or None when it is undefined.

    Undefined includes the case every practitioner forgets: if one side is
    entirely tied there is no rank variation and the correlation is not zero,
    it does not exist.
    """
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _ranks(list(xs)), _ranks(list(ys))
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denom = math.sqrt(sum((a - mx) ** 2 for a in rx)
                      * sum((b - my) ** 2 for b in ry))
    return None if denom == 0 else num / denom


def forward_return(prices_by_date: dict, as_of: str, horizon: int):
    """Total return over `horizon` trading bars after `as_of`.

    Bars are counted, not calendar days: 20 trading days is the horizon, and
    counting calendar days would silently vary the window with holidays.
    Returns None when the window does not close — a delisted name has no
    forward return, and imputing zero would flatter whichever bucket held it.
    """
    if not isinstance(prices_by_date, dict) or horizon <= 0:
        return None
    dated = sorted((d, _num(p)) for d, p in prices_by_date.items()
                   if isinstance(d, str) and _num(p) is not None and _num(p) > 0)
    at_or_before = [i for i, (d, _) in enumerate(dated) if d <= as_of]
    if not at_or_before:
        return None
    start = at_or_before[-1]
    end = start + horizon
    if end >= len(dated):
        return None
    return (dated[end][1] / dated[start][1]) - 1


def bucket_spread(scored, buckets: int = 5) -> dict:
    """Top-minus-bottom bucket mean forward return.

    `scored` is [(score, forward_return), ...]. Buckets are formed on score
    rank so they are equal-sized by construction.
    """
    rows = [(s, r) for s, r in scored
            if _num(s) is not None and _num(r) is not None]
    if len(rows) < buckets * 2:
        return {"spread": None, "reason": f"need >= {buckets * 2} names",
                "n": len(rows)}
    rows.sort(key=lambda item: item[0])
    size = len(rows) // buckets
    bottom = rows[:size]
    top = rows[-size:]
    mean_top = sum(r for _, r in top) / len(top)
    mean_bottom = sum(r for _, r in bottom) / len(bottom)
    return {
        "spread": mean_top - mean_bottom,
        "top_mean": mean_top, "bottom_mean": mean_bottom,
        "bucket_size": size, "n": len(rows),
    }


def turnover(previous_top, current_top) -> float | None:
    """Fraction of the top bucket replaced between snapshots — the cost driver."""
    previous, current = set(previous_top or []), set(current_top or [])
    if not current:
        return None
    return len(current - previous) / len(current)


def effective_sample_size(n_snapshots: int, horizon_days: int,
                          spacing_days: int) -> float | None:
    """Overlapping windows are not independent observations.

    Weekly snapshots (spacing 5) with a 20-day horizon overlap 4x, so 12
    snapshots carry roughly 3 independent windows. This is the crude standard
    adjustment, not a Newey-West correction, and it is deliberately
    conservative — the point is to stop a headline being computed on n=12 when
    the real n is 3.
    """
    if n_snapshots <= 0 or horizon_days <= 0 or spacing_days <= 0:
        return None
    return n_snapshots / max(1.0, horizon_days / spacing_days)


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------
def evaluate_snapshot(snapshot: dict, prices_by_ticker: dict,
                      horizon: int) -> dict:
    """One snapshot against realized prices, pooled by peer pool.

    The IC is computed WITHIN each pool and then size-weighted, because that is
    the comparison the score actually makes. A single cross-sectional IC over
    every name would mostly measure sector drift, not stock selection.
    """
    as_of = snapshot.get("as_of")
    by_pool = {}
    dropped = {"no_score": 0, "no_forward_price": 0}
    for entry in snapshot.get("entries") or []:
        score = _num(entry.get("experimental_score"))
        if score is None:
            dropped["no_score"] += 1
            continue
        realized = forward_return(prices_by_ticker.get(entry["ticker"]),
                                  as_of, horizon)
        if realized is None:
            dropped["no_forward_price"] += 1
            continue
        pool = entry.get("peer_pool") or entry.get("peer_level_used") or "unknown"
        by_pool.setdefault(pool, []).append((entry["ticker"], score, realized))

    pools, weighted, total_weight = [], 0.0, 0
    for pool, rows in sorted(by_pool.items()):
        if len(rows) < PROTOCOL["min_names_per_pool"]:
            pools.append({"pool": pool, "n": len(rows), "ic": None,
                          "reason": "below min_names_per_pool"})
            continue
        ic = spearman([r[1] for r in rows], [r[2] for r in rows])
        spread = bucket_spread([(r[1], r[2]) for r in rows],
                               PROTOCOL["buckets"])
        pools.append({"pool": pool, "n": len(rows), "ic": ic,
                      "spread": spread["spread"]})
        if ic is not None:
            weighted += ic * len(rows)
            total_weight += len(rows)

    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL["protocol_version"],
        "as_of": as_of,
        "horizon_trading_days": horizon,
        "pooled_ic": (weighted / total_weight) if total_weight else None,
        "names_evaluated": total_weight,
        "pools": pools,
        "dropped": dropped,
    }


def summarize(evaluations, spacing_days: int = 5) -> dict:
    """Across snapshots. Reports effective sample size and refuses a verdict
    before the pre-registered minimum."""
    ics = [e["pooled_ic"] for e in evaluations if e.get("pooled_ic") is not None]
    n = len(ics)
    horizon = evaluations[0]["horizon_trading_days"] if evaluations else 0
    mean_ic = sum(ics) / n if n else None
    n_eff = effective_sample_size(n, horizon, spacing_days)
    ready = n >= PROTOCOL["min_snapshots_before_reporting"]
    verdict = None
    if ready and mean_ic is not None:
        threshold = 0.02
        verdict = ("not predictive (within +/-0.02 of zero)"
                   if abs(mean_ic) <= threshold else
                   "signal present — needs an out-of-sample confirmation")
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL["protocol_version"],
        "protocol_hash": protocol_hash(),
        "snapshots_evaluated": n,
        "horizon_trading_days": horizon,
        "mean_ic": mean_ic,
        "hit_rate_positive_ic": (sum(1 for i in ics if i > 0) / n) if n else None,
        "effective_sample_size": n_eff,
        "min_snapshots_required": PROTOCOL["min_snapshots_before_reporting"],
        "ready_to_report": ready,
        "verdict": verdict,
        "caveat": ("overlapping windows; effective sample size is far below "
                   "the snapshot count and no significance claim is made"),
    }
