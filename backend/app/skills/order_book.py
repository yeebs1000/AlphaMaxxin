"""Order book depth summary — real Level 2 data via the moomoo OpenD
gateway (get_moomoo_orderbook, which needs an L2 entitlement on the user's
moomoo account). This is what turns the v1 "Global Order Book & Liquidity
Profiler" from a disabled lens into a live one: the analyst narrates these
computed numbers, it never imagines depth."""
from ..data.base import OfflineError


def summarize_depth(book: dict | None) -> dict | None:
    """Pure math over one get_moomoo_orderbook() result:
    {"best_bid","best_ask","spread","spread_bps","bid_depth","ask_depth",
    "imbalance","levels"} or None. imbalance is bid_depth/(bid+ask) — >0.5
    means resting buy interest outweighs sell interest in the visible book."""
    if not book or not book.get("bids") or not book.get("asks"):
        return None
    bids, asks = book["bids"], book["asks"]
    best_bid, best_ask = bids[0]["price"], asks[0]["price"]
    if not best_bid or not best_ask:
        return None
    mid = (best_bid + best_ask) / 2
    spread = best_ask - best_bid
    bid_depth = sum(level["volume"] for level in bids)
    ask_depth = sum(level["volume"] for level in asks)
    total = bid_depth + ask_depth
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": round(spread, 4),
        "spread_bps": round((spread / mid) * 10000, 1) if mid else None,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "imbalance": round(bid_depth / total, 3) if total else None,
        "levels": min(len(bids), len(asks)),
    }


def fetch_depth_summaries(tickers: list[str]) -> dict:
    """Per-ticker depth summaries from moomoo L2. Tickers without depth
    (unentitled market, moomoo down, offline tests) are simply absent —
    the lens prompt requires flagging missing tickers, not guessing."""
    out = {}
    try:
        from ..brokers.moomoo_client import get_moomoo_orderbook, MOOMOO_AVAILABLE
        if not MOOMOO_AVAILABLE:
            return out
        for ticker in tickers:
            summary = summarize_depth(get_moomoo_orderbook(ticker))
            if summary:
                out[ticker] = summary
    except (ImportError, OfflineError):
        pass
    return out
