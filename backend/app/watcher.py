"""Holdings watcher — the always-on junior analyst. Fired every 15 minutes by
Windows Task Scheduler (scripts/watch_holdings.cmd); exits instantly when no
held market is open, so off-hours spawns cost nothing.

Checks each holding whose market is open against the latest computed levels
(ledger's levels map), the day's move, and earnings proximity → one compact
Telegram alert, deduped per (ticker, trigger) per day. Stop/target breaches
can escalate to an auto-run Lite report (~2¢), capped per day — the only spend
in this module.

# ponytail: close-basis triggers on cached quotes; no intraday volume trigger
# (partial-day volume vs 20d average misleads). Add tick-level feeds if the
# 15-min cadence ever proves too coarse.
"""
import asyncio
import datetime
import json
import os
from pathlib import Path

from . import market_calendar as cal
from . import portfolio as pf

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = str(REPO_ROOT / "data_store" / "watcher_state.json")

BIG_MOVE_PCT = 5.0
EARNINGS_WITHIN_DAYS = 5
MAX_ESCALATIONS_PER_DAY = 2
_ESCALATABLE = {"stop_breach", "target_hit"}


def _load_state(file_path=None) -> dict:
    try:
        with open(file_path or STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state: dict, file_path=None) -> None:
    path = file_path or STATE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def check(holdings: list[dict], levels: dict, quotes: dict,
          earnings_dates: dict, state: dict,
          now: datetime.datetime) -> tuple[list[dict], dict]:
    """Pure trigger evaluation → (alerts, new_state). Skips tickers whose
    market is closed; dedupes per (ticker, trigger) per day via state."""
    today = now.date().isoformat()
    seen = set(state.get("alerted", {}).get(today, []))
    alerts = []
    for h in holdings:
        ticker = h["ticker"]
        if not cal.status_of_ticker(ticker, now=now)["is_open"]:
            continue
        quote = quotes.get(ticker) or {}
        price, change = quote.get("price"), quote.get("change_pct")
        lvl = levels.get(ticker) or {}

        fired = []
        if price and lvl.get("bear_stop") and price <= lvl["bear_stop"]:
            fired.append(("stop_breach",
                          f"🔴 {ticker} {price:.2f} ≤ stop {lvl['bear_stop']:.2f}"))
        elif price and lvl.get("base_target") and price >= lvl["base_target"]:
            fired.append(("target_hit",
                          f"🟢 {ticker} {price:.2f} ≥ target {lvl['base_target']:.2f}"))
        if change is not None and abs(change) >= BIG_MOVE_PCT:
            fired.append(("big_move", f"⚡ {ticker} {change:+.1f}% today"))
        edate = earnings_dates.get(ticker)
        if edate:
            days = (datetime.date.fromisoformat(edate) - now.date()).days
            if 0 <= days <= EARNINGS_WITHIN_DAYS:
                fired.append(("earnings_soon",
                              f"📅 {ticker} earnings {edate} ({days}d)"))

        for trigger, text in fired:
            key = f"{ticker}:{trigger}"
            if key not in seen:
                seen.add(key)
                alerts.append({"ticker": ticker, "trigger": trigger, "text": text})

    new_state = dict(state)
    new_state["alerted"] = {today: sorted(seen)}  # old days pruned
    new_state.setdefault("escalations", {})
    new_state["escalations"] = {today: new_state["escalations"].get(today, 0)}
    return alerts, new_state


def escalate(alerts: list[dict], state: dict, now: datetime.datetime,
             run_fn=None) -> tuple[list[str], dict]:
    """Run a Lite report on stop/target tickers, capped per day. run_fn is
    injectable for tests; returns (extra message lines, new_state)."""
    today = now.date().isoformat()
    used = state.get("escalations", {}).get(today, 0)
    lines = []
    for a in alerts:
        if a["trigger"] not in _ESCALATABLE or used >= MAX_ESCALATIONS_PER_DAY:
            continue
        try:
            result = (run_fn or _run_lite_report)(a["ticker"])
            if result:
                lines.append(result)
                used += 1
        except Exception as e:  # noqa: BLE001 — an escalation failure keeps alerts flowing
            print(f"[watcher] escalation for {a['ticker']} failed: {e}")
    new_state = dict(state)
    new_state.setdefault("escalations", {})[today] = used
    return lines, new_state


def _run_lite_report(ticker: str) -> str | None:
    """The ~2¢ spend: a Lite report on one ticker; returns its rec line."""
    from .data.registry import get_default_registry
    from .llm.costs import CostMeter
    from .reports import store
    from .reports.pipeline import run_report
    from .settings import load_settings

    report_id = asyncio.run(run_report(
        get_default_registry(),
        {"preset": "Lite", "target": {"kind": "tickers", "tickers": [ticker]}},
        lambda *a, **k: None, meter=CostMeter(), run_id=f"watcher-{ticker}",
        settings=load_settings()))
    report = store.load_report(report_id) or {}
    recs = report.get("sections", {}).get("synthesis", {}).get("recommendations", [])
    from .digest import _rec_line
    for r in recs:
        if r.get("ticker") == ticker:
            return f"↳ fresh read: {_rec_line(r)} (report {report_id})"
    return f"↳ fresh report saved: {report_id}"


def main() -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    holdings = pf.parse_portfolio()
    if not holdings:
        print("[watcher] no holdings — exiting")
        return
    open_holdings = [h for h in holdings
                     if cal.status_of_ticker(h["ticker"], now=now)["is_open"]]
    if not open_holdings:
        print("[watcher] no held market open — exiting")
        return

    from .data.live_quote import live_quote
    from .data.registry import get_default_registry
    from .reports import ledger
    from .skills import catalysts

    registry = get_default_registry()
    quotes = {h["ticker"]: live_quote(h["ticker"], registry.yahoo) or {}
              for h in open_holdings}
    levels = ledger._load()["levels"]
    calendar = catalysts.build_calendar(registry.finnhub,
                                        [h["ticker"] for h in open_holdings],
                                        horizon_days=EARNINGS_WITHIN_DAYS)
    earnings_dates = {e["ticker"]: e["date"] for e in calendar.get("events", [])
                      if e.get("type") == "earnings"}

    state = _load_state()
    alerts, state = check(open_holdings, levels, quotes, earnings_dates, state, now)
    if alerts:
        extra, state = escalate(alerts, state, now)
        message = "👀 AlphaMaxxin watcher\n" + "\n".join(
            [a["text"] for a in alerts] + extra)
        from .notify.telegram import send_message
        send_message(message)  # send before logging (cp1252 lesson)
        try:
            print(message)
        except UnicodeEncodeError:
            print(message.encode("ascii", "replace").decode("ascii"))
    else:
        print(f"[watcher] {len(open_holdings)} holdings checked — no triggers")
    _save_state(state)


if __name__ == "__main__":
    from .config import load_env
    load_env()
    main()
