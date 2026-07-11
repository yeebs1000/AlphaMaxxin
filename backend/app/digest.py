"""Daily digest — a short, glance-able Telegram message (NOT a full report):
a lite Opportunist scan for ideas worth noting + a Portfolio Medic watch-list.
For the full write-up the user opens the workstation.

Runs the existing report pipeline for each preset (so the numbers are the same
ones the app produces) and formats a compact message from the structured
`recommendations` — no extra LLM call beyond the runs themselves.

Entry point: `python -m app.digest`, fired by Windows Task Scheduler on this
machine (via scripts/daily_digest.cmd) so it can reach the LOCAL brokers —
Portfolio Medic syncs live positions first. Skips non-trading days. This spends
LLM tokens by design — the user authorised the scheduled run.
"""
import asyncio
import datetime

from . import market_calendar as cal
from . import portfolio as pf
from .reports import store
from .reports.pipeline import run_report

# Digest presets. Opportunist ignores the target (it scans); Portfolio Medic
# reads Portfolio.md (in CI, written from a secret before this runs).
_DIGEST_PRESETS = ("Opportunist", "Portfolio Medic")
_IDEAS_LIMIT = 6          # keep it glanceable
_BUY = {"buy", "accumulate"}
_TRIM = {"reduce", "sell"}


def _rec_line(r: dict) -> str:
    size = f" · {r['size']}" if r.get("size") else ""
    why = f" — {r['rationale']}" if r.get("rationale") else ""
    return f"• {r['ticker']} — {r.get('action', '?')} · {r.get('conviction', '?')}{size}{why}"


def _ledger_line(ledger_summary: dict | None) -> str | None:
    """One calibration line, only once calls have actually resolved."""
    by_conv = (ledger_summary or {}).get("by_conviction", {})
    parts = [f"{conv} {int(s['hit_rate'] * 100)}% hit ({s['resolved']} resolved)"
             for conv, s in by_conv.items()
             if s.get("resolved") and s.get("hit_rate") is not None]
    return "📒 Ledger: " + " · ".join(parts) if parts else None


def build_message(reports: dict, now: datetime.datetime | None = None,
                  ledger_summary: dict | None = None) -> str:
    """reports: {preset_name: report_dict}. → compact plain-text message."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    us, hk, sg = (cal.status("US", now), cal.status("HK", now), cal.status("SG", now))
    lines = [f"📊 AlphaMaxxin Daily — {now:%a %b %d}",
             f"Markets: US {'open' if us['is_open'] else 'closed'} · "
             f"HK {'open' if hk['is_open'] else 'closed'} · "
             f"SG {'open' if sg['is_open'] else 'closed'} "
             f"(last US session {us['last_trading_day']})", ""]

    opp = (reports.get("Opportunist") or {}).get("sections", {}).get("synthesis", {})
    ideas = [r for r in opp.get("recommendations", []) if r.get("action") in _BUY]
    lines.append("🔎 Worth noting (Opportunist scan)")
    lines += [_rec_line(r) for r in ideas[:_IDEAS_LIMIT]] or ["• (no high-conviction ideas today)"]
    lines.append("")

    med = (reports.get("Portfolio Medic") or {}).get("sections", {}).get("synthesis", {})
    watch = [r for r in med.get("recommendations", []) if r.get("action") in _TRIM]
    lines.append("🩺 Look out for (your holdings)")
    lines += [_rec_line(r) for r in watch[:_IDEAS_LIMIT]] or ["• nothing flagged to trim today"]
    ledger_line = _ledger_line(ledger_summary)
    if ledger_line:
        lines += ["", ledger_line]
    lines += ["", "Full report → run the workstation."]
    return "\n".join(lines)


async def _run_preset(preset: str) -> dict | None:
    """Run one report through the real pipeline; return the stored report dict.
    A failure in one preset must not sink the whole digest."""
    from .data.registry import get_default_registry
    from .llm.costs import CostMeter
    from .settings import load_settings
    try:
        report_id = await run_report(
            get_default_registry(), {"preset": preset, "target": {"kind": "portfolio"}},
            lambda *a, **k: None, meter=CostMeter(),
            run_id=f"digest-{preset}", settings=load_settings())
        return store.load_report(report_id)
    except Exception as e:  # noqa: BLE001 — digest resilience over strictness
        print(f"[digest] {preset} failed: {e}")
        return None


def _refresh_portfolio() -> None:
    """Pull live positions from the local brokers (moomoo/IBKR/Tiger) so
    Portfolio Medic sees the current book, not a stale file. Runs locally only
    — brokers are on this machine. Fails soft: if no broker is reachable, the
    existing Portfolio.md is used as-is."""
    try:
        result = pf.sync_from_brokers()
        print(f"[digest] broker sync: "
              f"{'ok' if result.get('success') else result.get('error')}")
    except Exception as e:  # noqa: BLE001 — never let a broker hiccup sink the digest
        print(f"[digest] broker sync failed, using existing Portfolio.md: {e}")


def _score_ledger() -> dict | None:
    """Daily conviction-ledger scoring — quote caches are warm from the report
    runs, so this is free. Fails soft."""
    from .data.live_quote import live_quote
    from .data.registry import get_default_registry
    from .reports import ledger
    try:
        registry = get_default_registry()
        ledger.score(lambda t: live_quote(t, registry.yahoo))
        return ledger.summary()
    except Exception as e:  # noqa: BLE001
        print(f"[digest] ledger scoring failed: {e}")
        return None


def run_digest(presets=_DIGEST_PRESETS, sender=None) -> str | None:
    """Run the presets, build the message, send it. Returns the message (or
    None if skipped). `sender` defaults to Telegram; tests pass a fake."""
    if not cal.is_trading_day("US"):
        print("[digest] non-trading day (US) — skipping")
        return None
    if "Portfolio Medic" in presets:
        _refresh_portfolio()
    reports = {p: asyncio.run(_run_preset(p)) for p in presets}
    ledger_summary = _score_ledger()
    message = build_message(reports, ledger_summary=ledger_summary)
    # Send first — a console/log encoding hiccup must never swallow delivery.
    if sender is None:
        from .notify.telegram import send_message as sender
    sender(message)
    # Then log it, encoding-safe: Windows' cp1252 stdout can't encode the emoji
    # in the message, which would otherwise raise UnicodeEncodeError.
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"))
    return message


if __name__ == "__main__":
    # This is a standalone entry point (not the API server), so load .env
    # ourselves — keys, broker ports, and Telegram creds all live there.
    from .config import load_env
    load_env()
    run_digest()
