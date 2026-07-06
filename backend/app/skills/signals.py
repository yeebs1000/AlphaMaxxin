"""Composite signal aggregation — replaces the v1 Quantitative Signal
Aggregator agent and the Dashboard's mechanical Position Guidance card with
transparent weighted math. Component scores are normalized to −100..+100
before blending."""
from ..data.base import to_number

# Component weights for the composite (sum to 1.0). Technicals dominate as
# the only per-ticker component that always exists; the others fold in when
# their data is present.
WEIGHTS = {"technical": 0.45, "fundamental": 0.25, "news": 0.15, "risk": 0.15}


def fundamental_score(snap: dict | None) -> int | None:
    """−100..+100 from the FundamentalsSnapshot's mechanical facts.

    Reads each numeric field through to_number() — a backstop, same as
    _quality_flags: the snapshot builder already coerces these, but this
    function must never crash on a bad type no matter how the snapshot was
    produced (stale cache, hand-built fixture, future caller)."""
    if not snap:
        return None
    score = 0
    flags = snap.get("quality_flags", [])
    score -= 20 * len(flags)
    rev_yoy = to_number((snap.get("growth") or {}).get("rev_yoy")) or 0
    if rev_yoy > 0.15:
        score += 25
    elif rev_yoy > 0.05:
        score += 10
    net = to_number((snap.get("margins") or {}).get("net")) or 0
    if net > 0.15:
        score += 20
    elif net > 0.05:
        score += 10
    analyst = snap.get("analyst") or {}
    target, price = to_number(analyst.get("target_mean")), to_number(snap.get("price"))
    if target and price:
        upside = (target - price) / price
        if upside > 0.20:
            score += 25
        elif upside > 0.05:
            score += 10
        elif upside < -0.05:
            score -= 15
    return max(-100, min(100, score))


def news_score(ticker: str, sentiment_by_ticker: dict | None) -> int | None:
    """−100..+100 from the news digest's per-ticker sentiment aggregate."""
    if not sentiment_by_ticker:
        return None
    agg = sentiment_by_ticker.get(ticker.replace(".SI", "").upper()) or \
        sentiment_by_ticker.get(ticker)
    if not agg or not agg.get("count"):
        return None
    return max(-100, min(100, int(agg["avg_score"] * 200)))


def risk_score(ticker: str, risk_report: dict | None) -> int | None:
    """−100..0 penalty from concentration/correlation involving this ticker."""
    if not risk_report:
        return None
    score = 0
    weight = risk_report.get("weights", {}).get(ticker, 0.0)
    if weight > 0.20:
        score -= 50
    elif weight > 0.10:
        score -= 20
    for pair in risk_report.get("high_correlation_pairs", []):
        if ticker in (pair["a"], pair["b"]):
            score -= 15
            break
    return max(-100, score)


def aggregate(ticker: str, technical_snap: dict | None,
              fundamentals_snap: dict | None = None,
              sentiment_by_ticker: dict | None = None,
              risk_report: dict | None = None) -> dict:
    """CompositeSignal: reweighted blend of whichever components have data.
    Conviction reflects both score magnitude and component coverage."""
    components = {
        "technical": (technical_snap or {}).get("signal", {}).get("score"),
        "fundamental": fundamental_score(fundamentals_snap),
        "news": news_score(ticker, sentiment_by_ticker),
        "risk": risk_score(ticker, risk_report),
    }
    present = {k: v for k, v in components.items() if v is not None}
    if not present:
        return {"ticker": ticker, "composite_score": None, "components": components,
                "conviction": "none", "coverage": 0}

    total_weight = sum(WEIGHTS[k] for k in present)
    composite = sum(WEIGHTS[k] * v for k, v in present.items()) / total_weight
    coverage = len(present) / len(WEIGHTS)

    magnitude = abs(composite)
    if magnitude >= 50 and coverage >= 0.75:
        conviction = "high"
    elif magnitude >= 30 and coverage >= 0.5:
        conviction = "medium"
    else:
        conviction = "low"

    return {"ticker": ticker, "composite_score": round(composite, 1),
            "components": components, "conviction": conviction,
            "coverage": round(coverage, 2)}


def recommendation_block(ticker: str, technical_snap: dict | None,
                         fundamentals_snap: dict | None = None,
                         atr_stop: float | None = None,
                         composite: dict | None = None) -> dict | None:
    """Standardized entry/target/stop block — every number here is derived
    from an already-computed real field (ATR, analyst consensus target, the
    sizing skill's ATR stop), never invented by an LLM. The synthesis
    prompt narrates this block; it doesn't set its own price levels."""
    price = (technical_snap or {}).get("last_close")
    atr = (technical_snap or {}).get("atr14")
    if price is None or atr is None:
        return None
    analyst_target = ((fundamentals_snap or {}).get("analyst") or {}).get("target_mean")
    bull_target = round(analyst_target, 2) if analyst_target else round(price + 3 * atr, 2)
    base_target = round((price + bull_target) / 2, 2)
    stop = atr_stop if atr_stop is not None else round(price - 2 * atr, 2)
    rr_base = round((base_target - price) / (price - stop), 2) if price > stop else None
    return {
        "ticker": ticker,
        "current_price": round(price, 2),
        "entry_range": [round(price - 0.5 * atr, 2), round(price + 0.5 * atr, 2)],
        "base_target": base_target,
        "bull_target": bull_target,
        "bear_stop": stop,
        "risk_reward_base": rr_base,
        "conviction": (composite or {}).get("conviction", "low"),
        "composite_score": (composite or {}).get("composite_score"),
        "target_source": "analyst consensus" if analyst_target
                         else "ATR-projected (no analyst target available this run)",
    }


def position_guidance(holdings: list[dict], snapshots: dict,
                      quotes: dict | None = None) -> list[dict]:
    """Free mechanical per-holding guidance (replaces gui.py's Position
    Guidance card): P&L, RSI, technical label."""
    out = []
    for h in holdings:
        ticker = h["ticker"]
        snap = snapshots.get(ticker)
        quote = (quotes or {}).get(ticker)
        price = quote["price"] if quote else (snap or {}).get("last_close")
        pl_pct = None
        if price and h.get("cost_price"):
            pl_pct = ((price - h["cost_price"]) / h["cost_price"]) * 100
        signal = (snap or {}).get("signal", {})
        out.append({
            "ticker": ticker,
            "company": h.get("company", ticker),
            "price": price,
            "pl_pct": pl_pct,
            "rsi14": (snap or {}).get("rsi14"),
            "score": signal.get("score"),
            "label": signal.get("label", "no data"),
            "reasons": signal.get("reasons", []),
        })
    return out
