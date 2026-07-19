"""24/7 market scanner — the always-on desk. One long-lived throttled loop
(freqtrade pattern, per research): scans each toggled market while its
exchange is in session, gates candidates through the cheap deterministic
pipeline first, and only sends *survivors* to the LLM — locally free when
LOCAL_LLM_BASE_URL is set, cloud-capped per day otherwise.

    python -m app.scanner          # foreground loop; Ctrl-C to stop
    (service-ify later: nssm install AlphaMaxxinScanner "py" "-m app.scanner")

Conviction gate (cheapest first, tuned to our own backtest evidence):
  1. screener momentum rank (region top slate, cached bars)
  2. mechanical signal in the PRODUCTIVE band (25–55: our quintile study
     showed extreme-high scores mean extended names that underperform)
     OR an RSI-reversion bullish setup (the one large measured edge, +2.9%)
  3. market-regime gate: the region's index above its 50d average
  4. chokepoint-universe membership adds priority, never bypasses gates
Survivors run through one batched Lite report (full lens/ledger machinery),
and alerts dedupe on (ticker, setup, direction) — one-shot, 1-trading-day
cooldown, re-arm only after the setup invalidates.

# ponytail: idle recheck every 15 min instead of computing exact next-open
# across five timezones; lunch breaks read as in-session (market_calendar
# ceiling). Upgrade: exchange_calendars if precision ever matters.
"""
import asyncio
import datetime
import json
import os
import random
import time
from pathlib import Path

from . import market_calendar as cal

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = str(REPO_ROOT / "data_store" / "scanner_state.json")
LOCK_FILE = str(REPO_ROOT / "data_store" / "scanner.lock")

WAKE_SECONDS = 60           # loop heartbeat
IDLE_RECHECK_SECONDS = 900  # all markets closed → nap
SIGNAL_BAND = (25, 55)      # productive mechanical-score band (backtest)
COOLDOWN_DAYS = 1
DEFAULTS = {"interval_min": 30, "max_cloud_runs_per_day": 4}


def _load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def gate_candidates(snapshots: dict, index_ok: bool) -> list[dict]:
    """Deterministic conviction gate over technicals snapshots → survivors
    [{ticker, setup, score, reasons}]. Pure — fully offline-testable."""
    if not index_ok:
        return []
    survivors = []
    for ticker, snap in snapshots.items():
        if not snap:
            continue
        sig = snap.get("signal") or {}
        score = sig.get("score")
        rsi = snap.get("rsi14")
        setups = []
        if rsi is not None and rsi < 30:
            setups.append("rsi_reversion")          # the measured +2.9% edge
        if score is not None and SIGNAL_BAND[0] <= score <= SIGNAL_BAND[1]:
            setups.append("productive_trend")       # Q3/Q4 band, not extended
        if not setups:
            continue
        from .skills.chokepoints import CHOKEPOINTS
        survivors.append({
            "ticker": ticker,
            "setup": "+".join(setups),
            "direction": "long",
            "score": score,
            "chokepoint": ticker in CHOKEPOINTS,
            "reasons": (sig.get("reasons") or [])[:3],
        })
    # Chokepoint names first, then by proximity to the band's sweet spot.
    survivors.sort(key=lambda s: (not s["chokepoint"], -(s["score"] or 0)))
    return survivors


def dedupe(survivors: list[dict], state: dict,
           today: datetime.date) -> tuple[list[dict], dict]:
    """One-shot per fingerprint with a cooldown floor; re-arms only when the
    setup stopped firing on a later scan (absence resets the fingerprint)."""
    fired = state.get("fired", {})   # fingerprint -> date fired
    fresh, seen_now = [], set()
    for s in survivors:
        fp = f"{s['ticker']}:{s['setup']}:{s['direction']}"
        seen_now.add(fp)
        if fp in fired:      # one-shot: stays disarmed while the setup persists
            continue
        fresh.append(s)
        fired[fp] = today.isoformat()
    # Re-arm: fingerprints that did NOT fire this scan have invalidated.
    for fp in list(fired):
        if fp not in seen_now:
            last = datetime.date.fromisoformat(fired[fp])
            if (today - last).days >= COOLDOWN_DAYS:
                del fired[fp]
    state["fired"] = fired
    return fresh, state


def _cloud_budget_ok(state: dict, today: datetime.date, settings: dict) -> bool:
    if os.environ.get("LOCAL_LLM_BASE_URL", "").strip():
        return True  # local inference is free
    runs = state.get("cloud_runs", {})
    used = runs.get(today.isoformat(), 0)
    return used < settings.get("max_cloud_runs_per_day",
                               DEFAULTS["max_cloud_runs_per_day"])


def _mark_cloud_run(state: dict, today: datetime.date) -> None:
    if os.environ.get("LOCAL_LLM_BASE_URL", "").strip():
        return
    runs = {today.isoformat(): state.get("cloud_runs", {}).get(today.isoformat(), 0) + 1}
    state["cloud_runs"] = runs


def scan_market(region: str, settings: dict) -> dict:
    """One market's cheap pipeline: screen → technicals → regime check.
    Returns {snapshots, index_ok}. Network-bound; every fetch is TTL-cached."""
    from .data.live_quote import live_ohlcv
    from .data.registry import get_default_registry
    from .skills import screener, technicals
    from .skills.macro import INDEX_SYMBOLS, REGION_KEYS

    registry = get_default_registry()
    slate = screener.screen(registry.yahoo, regions=[region],
                            max_per_market=8).get(region, [])
    snapshots = {}
    for row in slate:
        t = row["ticker"]
        daily = live_ohlcv(t, registry.yahoo, "1d", "1y")
        weekly = live_ohlcv(t, registry.yahoo, "1wk", "2y")
        snap = technicals.compute_snapshot(t, daily, weekly)
        if snap:
            snapshots[t] = snap
        time.sleep(random.uniform(0.4, 1.2))   # feed etiquette (jitter)

    index_symbol = INDEX_SYMBOLS.get(REGION_KEYS.get(region, {})
                                     .get("indices", [None])[0])
    index_ok = True
    if index_symbol:
        bars = registry.yahoo.ohlcv(index_symbol, "1d", "1y")
        closes = (bars or {}).get("closes") or []
        if len(closes) >= 50:
            index_ok = closes[-1] > sum(closes[-50:]) / 50
    return {"snapshots": snapshots, "index_ok": index_ok}


def _escalate(tickers: list[str]) -> str | None:
    """One batched Lite report over the survivors — full lens + ledger
    machinery, one LLM pass for the whole cycle."""
    from .data.registry import get_default_registry
    from .llm.costs import CostMeter
    from .reports.pipeline import run_report
    from .settings import load_settings
    return asyncio.run(run_report(
        get_default_registry(),
        {"preset": "Lite", "target": {"kind": "tickers", "tickers": tickers}},
        lambda *a, **k: None, meter=CostMeter(),
        run_id=f"scanner-{'-'.join(tickers[:3])}", settings=load_settings()))


def run_cycle(now: datetime.datetime | None = None) -> dict:
    """One pass over all toggled, in-session, interval-due markets."""
    from .notify.telegram import send_message
    from .settings import load_settings

    now = now or datetime.datetime.now(datetime.timezone.utc)
    settings = load_settings()
    scanner_cfg = {**DEFAULTS, **(settings.get("scanner") or {})}
    toggles = settings.get("scan_markets", {})
    state = _load_state()
    next_due = state.get("next_due", {})
    scanned, alerts_sent = [], 0

    for region in ("US", "SG", "HK", "JP", "KR"):
        if not toggles.get(region, True):
            continue
        if not cal.status(region, now)["is_open"]:
            continue
        due = next_due.get(region)
        if due and now.timestamp() < due:
            continue

        result = scan_market(region, settings)
        scanned.append(region)
        next_due[region] = now.timestamp() + scanner_cfg["interval_min"] * 60

        survivors = gate_candidates(result["snapshots"], result["index_ok"])
        fresh, state = dedupe(survivors, state, now.date())
        if not fresh:
            continue

        top = fresh[:3]   # never spam more than 3 setups per market per cycle
        lines = [f"🛰 Scanner — {region} session"] + [
            f"{'🎯' if s['chokepoint'] else '•'} {s['ticker']} "
            f"[{s['setup']}] score {s['score']}" for s in top]
        report_id = None
        if _cloud_budget_ok(state, now.date(), scanner_cfg):
            try:
                report_id = _escalate([s["ticker"] for s in top])
                _mark_cloud_run(state, now.date())
                lines.append(f"↳ full read saved: {report_id}")
            except Exception as e:  # noqa: BLE001
                lines.append(f"↳ read failed ({e}) — alert stands")
        else:
            lines.append("↳ cloud budget reached — deterministic alert only")
        send_message("\n".join(lines), topic="opportunist")
        alerts_sent += len(top)
        # Feed the dashboard: newest first, capped.
        latest = state.get("latest", [])
        for s in top:
            latest.insert(0, {**s, "region": region, "report_id": report_id,
                              "at": now.isoformat()})
        state["latest"] = latest[:20]

    state["next_due"] = next_due
    _save_state(state)
    return {"scanned": scanned, "alerts": alerts_sent}


def main() -> None:
    # Single instance via lockfile (IP-level feed bans punish the whole
    # machine, so two scanners is strictly worse than none).
    if os.path.exists(LOCK_FILE):
        print(f"[scanner] lock file exists — another scanner may be running. "
              f"Delete {LOCK_FILE} if not.")
        return
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    open(LOCK_FILE, "w").write(str(os.getpid()))
    print("[scanner] running — Ctrl-C to stop")
    try:
        while True:
            any_open = any(cal.status(r)["is_open"]
                           for r in ("US", "SG", "HK", "JP", "KR"))
            if not any_open:
                time.sleep(IDLE_RECHECK_SECONDS)
                continue
            try:
                out = run_cycle()
                if out["scanned"]:
                    print(f"[scanner] scanned {out['scanned']}, "
                          f"{out['alerts']} alerts")
            except Exception as e:  # noqa: BLE001 — the loop must survive
                print(f"[scanner] cycle failed: {e}")
                time.sleep(300)     # circuit-breaker nap on repeated trouble
            time.sleep(WAKE_SECONDS)
    finally:
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    from .config import load_env
    load_env()
    main()
