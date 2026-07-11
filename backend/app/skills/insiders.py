"""Insider-transaction digest — corporate Form 4 activity per ticker, the
company-officer sibling of politician_trades. Only open-market purchases (code
P) and sales (S) count: gifts, option exercises, awards, and tax withholding
(G/M/A/F) are administrative noise, not conviction. A "cluster" (≥3 distinct
open-market buyers in 90 days) is the pattern with actual literature behind it.
"""
import datetime

WINDOW_DAYS = 90
CLUSTER_BUYERS = 3


def digest_transactions(rows: list[dict], today: datetime.date | None = None) -> dict:
    """Raw finnhub insider rows → compact per-ticker summary."""
    today = today or datetime.date.today()
    cutoff = today - datetime.timedelta(days=WINDOW_DAYS)
    buys, sells = [], []
    for r in rows:
        code = r.get("transactionCode")
        if code not in ("P", "S"):
            continue
        try:
            tdate = datetime.date.fromisoformat(r.get("transactionDate") or "")
        except ValueError:
            continue
        if tdate < cutoff:
            continue
        (buys if code == "P" else sells).append(r)

    buyer_names = {r.get("name") for r in buys if r.get("name")}
    net_shares = (sum(abs(r.get("change") or 0) for r in buys)
                  - sum(abs(r.get("change") or 0) for r in sells))
    return {
        "window_days": WINDOW_DAYS,
        "open_market_buys": len(buys),
        "open_market_sells": len(sells),
        "distinct_buyers": len(buyer_names),
        "net_shares": net_shares,
        "cluster_buying": len(buyer_names) >= CLUSTER_BUYERS,
        "latest_buy": max((r["transactionDate"] for r in buys), default=None),
        "latest_sell": max((r["transactionDate"] for r in sells), default=None),
    }


def fetch_insiders(finnhub, tickers: list[str],
                   today: datetime.date | None = None) -> dict:
    """{ticker: digest} for tickers with any qualifying activity; a feed_ok
    flag so the lens can distinguish 'quiet' from 'feed down'."""
    out: dict = {"by_ticker": {}, "feed_ok": bool(finnhub.available)}
    if not finnhub.available:
        return out
    for t in tickers:
        d = digest_transactions(finnhub.insider_transactions(t), today=today)
        if d["open_market_buys"] or d["open_market_sells"]:
            out["by_ticker"][t] = d
    return out
