"""AlphaMaxxin MCP server — exposes the deterministic skills as read-only
tools over stdio, so any MCP client (Claude Code, Claude Desktop, other
agents) can query the live book, ledger, technicals, macro, and backtest
results directly.

Register with Claude Code (from the backend/ directory):

    claude mcp add alphamaxxin -- py -m app.mcp_server

Every tool is read-only and costs $0 — they serve computed data from the free
feeds (disk-cached). Deliberately NOT exposed: anything that spends LLM money
(run_report) or changes state (watchlists, portfolio edits, scheduled tasks).
An agent querying the workstation shouldn't be able to bill the user or
mutate the book; those stay human-triggered in the app.
"""
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_FILE = str(REPO_ROOT / "data_store" / "backtest_results.json")

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False,
              "idempotentHint": True, "openWorldHint": False}

mcp = FastMCP("alphamaxxin_mcp")


def _registry():
    from .data.registry import get_default_registry
    return get_default_registry()


@mcp.tool(annotations={"title": "Get portfolio", **_READ_ONLY})
def get_portfolio() -> dict:
    """Current holdings with live valuation: per-position value/weight/P&L in
    USD, day change, totals. Reads Portfolio.md (kept in sync from the
    brokers by the daily digest)."""
    from . import portfolio as pf
    from .data.live_quote import live_quote
    from .skills import performance
    holdings = pf.parse_portfolio()
    if not holdings:
        return {"error": "Portfolio.md is empty — sync brokers in the app first"}
    registry = _registry()
    quotes = {h["ticker"]: live_quote(h["ticker"], registry.yahoo) or {}
              for h in holdings}
    fx = {}
    for ccy in {h.get("currency", "USD") for h in holdings}:
        if ccy != "USD":
            rate = registry.yahoo.fx_rate(ccy)
            if rate:
                fx[ccy] = rate
    return performance.portfolio_summary(holdings, quotes, fx_rates=fx)


@mcp.tool(annotations={"title": "Get conviction ledger", **_READ_ONLY})
def get_ledger() -> dict:
    """Every recommendation the reports have made, scored against real prices:
    open/resolved entries, latest per-ticker levels (stop/target), and hit-rate
    calibration by conviction level."""
    from .data.live_quote import live_quote
    from .reports import ledger
    registry = _registry()
    data = ledger.score(lambda t: live_quote(t, registry.yahoo))
    return {"entries": data["entries"], "levels": data["levels"],
            "summary": ledger.summary()}


@mcp.tool(annotations={"title": "Get technicals for a ticker", **_READ_ONLY})
def get_technicals(ticker: str) -> dict:
    """Full technical snapshot for one ticker: indicators (RSI, MACD,
    SMAs/EMA, Bollinger, ATR, volume profile), candle patterns, the mechanical
    -100..+100 signal with reasons, and the 7-strategy panel verdicts."""
    from .data.live_quote import live_ohlcv
    from .skills import strategies, technicals
    registry = _registry()
    daily = live_ohlcv(ticker, registry.yahoo, "1d", "1y")
    weekly = live_ohlcv(ticker, registry.yahoo, "1wk", "2y")
    snap = technicals.compute_snapshot(ticker.upper(), daily, weekly)
    if not snap:
        return {"error": f"no price history for '{ticker}' — check the symbol"}
    panel = strategies.panel([snap["ticker"]], {snap["ticker"]: snap})
    return {"snapshot": snap, "strategy_panel": panel.get(snap["ticker"])}


@mcp.tool(annotations={"title": "Get macro snapshot", **_READ_ONLY})
def get_macro() -> dict:
    """US macro backdrop from FRED + live markets: rates/curve, CPI & PPI,
    NFP, unemployment, Fed balance sheet, the Fed dot plot vs market pricing,
    regime flags, and regional momentum signals."""
    from .skills import macro
    registry = _registry()
    return macro.compute_macro(registry.fred, registry.yahoo,
                               regions=["US", "HK", "SG", "JP", "KR"])


@mcp.tool(annotations={"title": "Get supply-chain flow", **_READ_ONLY})
def get_supply_chain() -> dict:
    """Tier momentum across curated value chains (memory/semis, data centers,
    optics, EV): median 3-month momentum per tier and early/late-cycle
    divergence reads."""
    from .skills import supply_chain
    return supply_chain.compute_chains(_registry().yahoo)


@mcp.tool(annotations={"title": "Get backtest results", **_READ_ONLY})
def get_backtest_results() -> dict:
    """Latest saved signal-stack backtest: per-strategy forward-return edge vs
    baseline, mechanical-score quintiles, stop/target resolution stats.
    Regenerate with `python scripts/backtest_signals.py` (data APIs only)."""
    try:
        with open(BACKTEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"error": "no saved results — run scripts/backtest_signals.py first"}


@mcp.tool(annotations={"title": "Get book equity history", **_READ_ONLY})
def get_equity_history() -> dict:
    """The book's own daily value snapshots and derived performance
    (deposit-adjusted TWR, max drawdown, Sharpe/Sortino). Needs ≥5 snapshots;
    the weekday digest records one per day."""
    from . import equity_history
    m = equity_history.metrics()
    rows = equity_history._load()
    return {"metrics": m or "insufficient history (<5 snapshots)",
            "recent_snapshots": rows[-10:]}


@mcp.tool(annotations={"title": "List saved reports", **_READ_ONLY})
def list_reports(limit: int = 10) -> dict:
    """Index of stored research reports, newest first: id, preset, target,
    created_at, recommendation count, cost."""
    from .reports import store
    return {"reports": store.list_reports()[:max(1, min(limit, 50))]}


@mcp.tool(annotations={"title": "Get a saved report", **_READ_ONLY})
def get_report(report_id: str, include_skills: bool = False) -> dict:
    """One stored report: synthesis markdown + recommendations, analyst
    findings, and lens status. Set include_skills=true for the full computed
    skills payload (large)."""
    from .reports import store
    report = store.load_report(report_id)
    if not report:
        return {"error": f"report '{report_id}' not found — see list_reports"}
    if not include_skills:
        report = {**report, "sections": {**report["sections"], "skills": "omitted"}}
    return report


if __name__ == "__main__":
    from .config import load_env
    load_env()  # standalone entry point — keys/broker ports come from .env
    mcp.run()   # stdio transport
