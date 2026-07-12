"""Event-study backtest of the deterministic signal stack — replays history
through the SAME code paths the app uses live (technicals.compute_snapshot →
mechanical signal, strategies.run_strategies, signals.recommendation_block),
so what's measured is what ships. At each sampled bar the stack sees history
up to that bar only; outcomes come from the bars after it.

Honest scope: event-study statistics (per-signal forward-return edge vs
baseline, stop-vs-target resolution), NOT a portfolio simulation — no sizing,
costs, or overlapping-position netting. Fundamentals/news aren't replayed
(no free point-in-time source), so fundamentals-dependent strategies simply
don't fire, and recommendation blocks use their ATR fallback targets — same
degraded mode the live app runs in when those feeds are down.
# ponytail: same-day stop+target touch counts as a stop (worst case);
# portfolio sim with sizing/costs is the upgrade if these stats earn it.
"""
import numpy as np

from . import strategies as strat_skill
from . import technicals
from .signals import recommendation_block

MIN_HISTORY = 200          # bars before the first event (SMA200 needs it)
WINDOW = 260               # ~1y of daily bars — the same lookback the live app
                           # fetches, so backtested indicators match production
DEFAULT_HORIZONS = (20, 60)
RESOLUTION_WINDOW = 60     # days a stop/target has to resolve


def _weekly_from_daily(closes: list) -> dict:
    return {"closes": list(closes[::5])}


def collect_events(ticker: str, bars: dict, step: int = 5,
                   horizons=DEFAULT_HORIZONS) -> list[dict]:
    """One event per sampled bar: the stack's outputs at that bar plus
    forward outcomes. History-only inputs; future bars only in outcomes."""
    closes, highs = bars["closes"], bars["highs"]
    lows, volumes = bars["lows"], bars["volumes"]
    opens = bars.get("opens")
    max_h = max(max(horizons), RESOLUTION_WINDOW)
    events = []
    for i in range(MIN_HISTORY - 1, len(closes) - max_h, step):
        start = max(0, i + 1 - WINDOW)
        daily = {"closes": closes[start:i + 1], "highs": highs[start:i + 1],
                 "lows": lows[start:i + 1], "volumes": volumes[start:i + 1]}
        if opens:
            daily["opens"] = opens[start:i + 1]
        snap = technicals.compute_snapshot(ticker, daily,
                                           _weekly_from_daily(daily["closes"]))
        if not snap or snap.get("atr14") is None:
            continue
        block = recommendation_block(ticker, snap)
        price = closes[i]

        fwd = {h: (closes[i + h] / price - 1.0) if price else None for h in horizons}
        resolution = "none"
        if block:
            for j in range(i + 1, i + 1 + RESOLUTION_WINDOW):
                hit_stop = lows[j] <= block["bear_stop"]
                hit_target = highs[j] >= block["base_target"]
                if hit_stop:            # same-day double touch counts as stop
                    resolution = "stop"
                    break
                if hit_target:
                    resolution = "target"
                    break

        verdicts = strat_skill.run_strategies({"technicals": snap})
        events.append({
            "ticker": ticker, "bar": i,
            "mech_score": snap["signal"]["score"],
            "strategies": {v["name"]: v["stance"] for v in verdicts},
            "fwd": fwd,
            "resolution": resolution,
        })
    return events


def aggregate(events: list[dict], horizons=DEFAULT_HORIZONS) -> dict:
    """Per-strategy edge vs baseline, mechanical-score quintile monotonicity,
    and stop/target resolution rates."""
    if not events:
        return {"n_events": 0}
    out: dict = {"n_events": len(events)}

    baseline = {h: float(np.mean([e["fwd"][h] for e in events
                                  if e["fwd"][h] is not None])) for h in horizons}
    out["baseline_fwd"] = {h: round(b * 100, 3) for h, b in baseline.items()}

    strat_stats: dict = {}
    for name in {n for e in events for n in e["strategies"]}:
        for stance in ("bullish", "bearish"):
            sel = [e for e in events if e["strategies"].get(name) == stance]
            if len(sel) < 30:  # too few events for a meaningful stat
                continue
            stats = {"n": len(sel)}
            for h in horizons:
                rets = [e["fwd"][h] for e in sel if e["fwd"][h] is not None]
                mean = float(np.mean(rets))
                # edge = how much better (bullish) / worse (bearish) than baseline
                stats[f"fwd{h}_pct"] = round(mean * 100, 3)
                stats[f"edge{h}_pct"] = round((mean - baseline[h]) * 100, 3)
            stats["win_rate_60d"] = round(
                float(np.mean([e["fwd"][60] > 0 for e in sel
                               if e["fwd"].get(60) is not None])), 3)
            strat_stats[f"{name} ({stance})"] = stats
    out["strategies"] = strat_stats

    # Mechanical score quintiles → does a higher score mean higher forward return?
    scores = np.array([e["mech_score"] for e in events], dtype=float)
    fwd60 = np.array([e["fwd"].get(60) if e["fwd"].get(60) is not None else np.nan
                      for e in events])
    edges = np.quantile(scores, [0.2, 0.4, 0.6, 0.8])
    quintiles = []
    for q, (lo, hi) in enumerate(zip([-np.inf, *edges], [*edges, np.inf]), 1):
        mask = (scores > lo) & (scores <= hi) & ~np.isnan(fwd60)
        if mask.sum():
            quintiles.append({"q": q, "n": int(mask.sum()),
                              "score_range": [round(float(max(lo, scores.min())), 1),
                                              round(float(min(hi, scores.max())), 1)],
                              "fwd60_pct": round(float(np.mean(fwd60[mask])) * 100, 3)})
    out["score_quintiles"] = quintiles
    means = [q["fwd60_pct"] for q in quintiles]
    out["score_monotonic"] = bool(all(b >= a for a, b in zip(means, means[1:]))) \
        if len(means) >= 2 else None

    resolved = [e["resolution"] for e in events]
    n_stop, n_target = resolved.count("stop"), resolved.count("target")
    out["stop_target"] = {
        "n": len(resolved), "stop_first": n_stop, "target_first": n_target,
        "unresolved_60d": resolved.count("none"),
        "target_rate": round(n_target / (n_stop + n_target), 3)
                       if (n_stop + n_target) else None,
    }
    return out


def run(bars_by_ticker: dict, step: int = 5, horizons=DEFAULT_HORIZONS) -> dict:
    events = []
    for ticker, bars in bars_by_ticker.items():
        if bars and len(bars.get("closes", [])) > MIN_HISTORY + RESOLUTION_WINDOW:
            events.extend(collect_events(ticker, bars, step=step, horizons=horizons))
    return aggregate(events, horizons=horizons)


def format_report(results: dict) -> str:
    """Plain-text summary table of aggregate() output."""
    if not results.get("n_events"):
        return "No events — not enough history."
    lines = [f"Events: {results['n_events']}   "
             f"baseline fwd: {results['baseline_fwd']}",
             "", f"{'strategy':34}{'n':>7}{'fwd60%':>9}{'edge60%':>9}{'win60':>7}"]
    for name, s in sorted(results["strategies"].items(),
                          key=lambda kv: -kv[1].get("edge60_pct", 0)):
        lines.append(f"{name:34}{s['n']:>7}{s.get('fwd60_pct', 0):>9.2f}"
                     f"{s.get('edge60_pct', 0):>9.2f}{s.get('win_rate_60d', 0):>7.2f}")
    lines += ["", "mechanical-score quintiles (fwd 60d %):",
              "  " + "  ".join(f"Q{q['q']}:{q['fwd60_pct']:+.2f}"
                               for q in results["score_quintiles"]),
              f"  monotonic: {results['score_monotonic']}",
              "", f"stop/target (ATR blocks): {results['stop_target']}"]
    return "\n".join(lines)
