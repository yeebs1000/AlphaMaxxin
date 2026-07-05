"""Portfolio.md parse/save + multi-broker sync — port of runner.py's
portfolio functions. Parsing/merging math is unchanged (v1 behavior is the
spec); save_portfolio takes pre-fetched quotes instead of fetching inline.
"""
import datetime
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PORTFOLIO_FILE = str(REPO_ROOT / "Portfolio.md")
EXTERNAL_HOLDINGS_FILE = str(REPO_ROOT / "external_holdings.json")

_MARKET_CCY = {"US": "USD", "SG": "SGD", "HK": "HKD", "SH": "CNY", "SZ": "CNY",
               "MY": "MYR", "JP": "JPY"}

_CURRENCY_SECTION_TITLES = {
    "SGD": "🇸🇬 Singapore Equities (SGD)",
    "USD": "🇺🇸 US Equities & ETFs (USD)",
    "HKD": "🇭🇰 Hong Kong Equities (HKD)",
}


def parse_portfolio(file_path=None) -> list[dict]:
    """Parse Portfolio.md markdown tables into
    [{company, ticker, quantity, cost_price, currency}]. Currency comes from
    the section headers (same detection rules as v1's parse_portfolio_full,
    extended with HKD)."""
    file_path = file_path or PORTFOLIO_FILE
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    holdings = []
    current_section = "USD"
    for line in content.split("\n"):
        line_strip = line.strip()

        if "Singapore" in line_strip and "SGD" in line_strip:
            current_section = "SGD"
        elif "Hong Kong" in line_strip and "HKD" in line_strip:
            current_section = "HKD"
        elif "US" in line_strip and ("USD" in line_strip or "ETF" in line_strip):
            current_section = "USD"

        if not line_strip.startswith("|") or not line_strip.endswith("|"):
            continue
        parts = [p.strip() for p in line_strip.split("|")[1:-1]]
        if len(parts) < 6:
            continue
        if any(h in parts[0].lower() for h in ["company", "---", ":"]):
            continue
        if "total" in parts[0].lower() or parts[0] == "":
            continue

        company = parts[0].replace("**", "").replace("*", "").strip()
        ticker = parts[1].replace("**", "").strip()
        qty_str = parts[2].replace("**", "").replace(",", "").strip()
        cost_str = parts[4].replace("**", "").replace(",", "").strip()
        try:
            holdings.append({
                "company": company,
                "ticker": ticker,
                "quantity": float(qty_str),
                "cost_price": float(cost_str) if cost_str else 0.0,
                "currency": current_section,
            })
        except ValueError:
            continue
    return holdings


def save_portfolio(holdings: list[dict], file_path=None,
                   quotes: dict | None = None) -> None:
    """Write holdings to Portfolio.md, one table section per currency —
    same format v1 wrote and the legacy GUI still reads. quotes ({ticker:
    {"price": ...}}) supplies Current Price; missing quotes fall back to
    cost basis, same as v1's failed-fetch behavior."""
    file_path = file_path or PORTFOLIO_FILE
    quotes = quotes or {}

    currencies_in_order = []
    for h in holdings:
        ccy = h.get("currency", "USD")
        if ccy not in currencies_in_order:
            currencies_in_order.append(ccy)

    today = datetime.date.today().strftime("%B %d, %Y")
    lines = ["# Investment Portfolio", "", f"> **Last Updated:** {today}", "", "---", ""]

    for ccy in currencies_in_order:
        section = [h for h in holdings if h.get("currency", "USD") == ccy]
        if not section:
            continue
        title = _CURRENCY_SECTION_TITLES.get(ccy, f"{ccy} Equities")
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| Company | Ticker | Quantity | Current Price | Cost Price | Market Value | Total P/L |")
        lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: |")
        total_val = total_pl = 0.0
        for h in section:
            qty, cost = h["quantity"], h["cost_price"]
            quote = quotes.get(h["ticker"])
            cur_price = quote["price"] if quote and quote.get("price") else cost
            market_val = qty * cur_price
            pl = (cur_price - cost) * qty
            total_val += market_val
            total_pl += pl
            pl_str = f"+{pl:,.2f}" if pl >= 0 else f"{pl:,.2f}"
            qty_str = f"{qty:,.1f}" if qty != int(qty) else f"{int(qty):,}"
            lines.append(
                f"| **{h['company']}** | {h['ticker']} | {qty_str} | {cur_price:.3f} "
                f"| {cost:.3f} | {market_val:,.2f} | {pl_str} |")
        pl_total_str = f"+{total_pl:,.2f}" if total_pl >= 0 else f"{total_pl:,.2f}"
        lines.append(f"| **Total ({ccy})** | | | | | **{total_val:,.2f}** | **{pl_total_str}** |")
        lines.append("")
        lines.append("---")
        lines.append("")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def load_external_holdings(file_path=None) -> dict:
    """Optional manual supplement for brokers without a live integration.
    {} when absent."""
    file_path = file_path or EXTERNAL_HOLDINGS_FILE
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_holding(merged: dict, ticker: str, company: str, qty: float,
                  cost: float, currency: str) -> None:
    """Same ticker from two sources → summed quantity, weighted-average cost."""
    if ticker in merged:
        existing = merged[ticker]
        total_qty = existing["quantity"] + qty
        existing["cost_price"] = (
            (existing["quantity"] * existing["cost_price"] + qty * cost) / total_qty
            if total_qty else 0.0
        )
        existing["quantity"] = total_qty
    else:
        merged[ticker] = {"company": company or ticker, "ticker": ticker,
                          "quantity": qty, "cost_price": cost, "currency": currency}


def sync_from_brokers(external_path=None, file_path=None,
                      quotes: dict | None = None) -> dict:
    """Rebuild Portfolio.md from every reachable broker (moomoo/IBKR/Tiger)
    plus external_holdings.json. Same success/error semantics as v1."""
    merged: dict = {}
    sources_tried = sources_ok = 0

    try:
        from .brokers.moomoo_client import get_moomoo_positions, MOOMOO_AVAILABLE
        if MOOMOO_AVAILABLE:
            sources_tried += 1
            positions = get_moomoo_positions()
            if positions is not None:
                sources_ok += 1
                for p in positions:
                    market, _, ticker = p["code"].partition(".")
                    merge_holding(merged, ticker, p["name"], p["qty"],
                                  p["average_cost"], _MARKET_CCY.get(market, "USD"))
    except ImportError:
        pass

    try:
        from .brokers.ibkr_client import get_ibkr_positions, IBKR_AVAILABLE
        if IBKR_AVAILABLE:
            sources_tried += 1
            positions = get_ibkr_positions()
            if positions is not None:
                sources_ok += 1
                for p in positions:
                    merge_holding(merged, p["ticker"], p["company"], p["quantity"],
                                  p["cost_price"], p["currency"])
    except ImportError:
        pass

    try:
        from .brokers.tiger_client import get_tiger_positions, TIGER_AVAILABLE
        if TIGER_AVAILABLE:
            sources_tried += 1
            positions = get_tiger_positions()
            if positions is not None:
                sources_ok += 1
                for p in positions:
                    merge_holding(merged, p["ticker"], p["company"], p["quantity"],
                                  p["cost_price"], p["currency"])
    except ImportError:
        pass

    external = load_external_holdings(external_path)
    if external:
        sources_tried += 1
        sources_ok += 1
        for ticker, ext in external.items():
            merge_holding(merged, ticker, ext.get("company", ticker),
                          float(ext["quantity"]), float(ext.get("cost_price", 0)),
                          ext.get("currency", "USD"))

    if sources_tried == 0:
        return {"success": False, "holdings": [],
                "error": "No broker configured — see README.md's \"Linking your broker\" section."}
    if sources_ok == 0:
        return {"success": False, "holdings": [],
                "error": "Could not reach any configured broker — check it's running/logged in."}

    holdings = list(merged.values())
    save_portfolio(holdings, file_path=file_path, quotes=quotes)
    return {"success": True, "holdings": holdings, "error": None}
