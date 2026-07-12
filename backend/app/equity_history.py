"""Daily equity snapshots of the actual book — what the holdings' price
series can't show: YOUR portfolio's value over time, drawdown, and
risk-adjusted return. Recorded automatically on every portfolio report run
(the digest makes that daily on weekdays).

Return methodology (honest ceiling): true time-weighted return needs dated
cashflows we don't track. Approximation: each snapshot stores value AND cost
basis; the day's return strips the cost-basis delta (deposits/new buys) out
of the value change — deposit-blind enough for a personal book. Snapshots are
per-run-day; gaps (weekends, missed days) are treated as single periods.
"""
import datetime
import json
import os
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
EQUITY_FILE = str(REPO_ROOT / "data_store" / "equity_history.json")


def _path(file_path=None) -> str:
    # Env override so the offline test suite (whose pipeline runs hit the
    # recording hook) never writes the real data_store file.
    return file_path or os.environ.get("ALPHAMAXXIN_EQUITY_FILE") or EQUITY_FILE


def _load(file_path=None) -> list[dict]:
    try:
        with open(_path(file_path), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def record(summary: dict, file_path=None,
           today: datetime.date | None = None) -> None:
    """Upsert today's snapshot from a portfolio_summary(). Failure-soft and
    idempotent per day (last run of the day wins)."""
    try:
        value = summary.get("total_value_usd")
        if not value or value <= 0:
            return
        today = today or datetime.date.today()
        rows = [r for r in _load(file_path) if r.get("date") != today.isoformat()]
        rows.append({"date": today.isoformat(),
                     "value_usd": round(value, 2),
                     "cost_usd": round(summary.get("total_cost_usd") or 0, 2),
                     "holdings_count": summary.get("holdings_count")})
        rows.sort(key=lambda r: r["date"])
        path = _path(file_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)
    except Exception as e:  # noqa: BLE001 — never sink a report run
        print(f"[equity] snapshot failed (run unaffected): {e}")


def metrics(file_path=None) -> dict | None:
    """Book-level performance from the snapshot series, or None with <5
    points (too little history to say anything honest)."""
    rows = _load(file_path)
    if len(rows) < 5:
        return None
    values = np.array([r["value_usd"] for r in rows], dtype=float)
    costs = np.array([r.get("cost_usd") or 0 for r in rows], dtype=float)

    # Deposit-adjusted period returns: strip the cost-basis change out of the
    # value change so new money doesn't masquerade as performance.
    flows = np.diff(costs)
    rets = (np.diff(values) - flows) / values[:-1]
    equity = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(equity)

    mean, std = float(np.mean(rets)), float(np.std(rets, ddof=1))
    downside = rets[rets < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else None
    return {
        "n_snapshots": len(rows),
        "first_date": rows[0]["date"],
        "last_date": rows[-1]["date"],
        "twr_pct": round(float(equity[-1] - 1) * 100, 2),
        "max_drawdown_pct": round(float(np.min(equity / peak - 1)) * 100, 2),
        "sharpe_ann": round(mean / std * np.sqrt(252), 2) if std > 0 else None,
        "sortino_ann": round(mean / downside_std * np.sqrt(252), 2)
                       if downside_std and downside_std > 0 else None,
        "note": "snapshot-based TWR, deposit-adjusted via cost-basis deltas",
    }
