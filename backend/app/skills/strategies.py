"""Strategy panel — a library of named, well-known trading strategies, each
evaluated in CODE from data the skills layer already computed (technicals,
fundamentals, composite). This is the "agent-first, token-cheap" answer: adding
strategies costs zero extra LLM tokens because they run deterministically; the
existing analyst lens just narrates the compact verdict table.

Each strategy is a pure function ctx→verdict|None (None = not applicable /
insufficient data). Add a strategy by writing one function and listing it in
STRATEGIES — no other wiring.
"""

# --- individual strategies (each returns {name, stance, score, reason} or None) ---
# stance ∈ {bullish, bearish, neutral}; score ∈ [-100, 100].


def _v(name, stance, score, reason):
    return {"name": name, "stance": stance, "score": score, "reason": reason}


def ma_crossover(ctx) -> dict | None:
    """Golden/death cross: 50-day SMA vs 200-day SMA."""
    t = ctx.get("technicals") or {}
    s50, s200 = t.get("sma50"), t.get("sma200")
    if s50 is None or s200 is None:
        return None
    if s50 > s200:
        return _v("MA Crossover", "bullish", 40, f"50DMA {s50:.2f} > 200DMA {s200:.2f} (golden)")
    return _v("MA Crossover", "bearish", -40, f"50DMA {s50:.2f} < 200DMA {s200:.2f} (death)")


def rsi_reversion(ctx) -> dict | None:
    """Mean reversion off RSI extremes."""
    rsi = (ctx.get("technicals") or {}).get("rsi14")
    if rsi is None:
        return None
    if rsi < 30:
        return _v("RSI Reversion", "bullish", 35, f"RSI {rsi:.0f} oversold")
    if rsi > 70:
        return _v("RSI Reversion", "bearish", -35, f"RSI {rsi:.0f} overbought")
    return None  # only fires at extremes


def macd_momentum(ctx) -> dict | None:
    macd = (ctx.get("technicals") or {}).get("macd")
    if not macd:
        return None
    h = macd["histogram"]
    return _v("MACD Momentum", "bullish" if h > 0 else "bearish",
              30 if h > 0 else -30, f"MACD histogram {h:+.3f}")


def trend_following(ctx) -> dict | None:
    """Price vs 200DMA confirmed by the higher-timeframe trend."""
    t = ctx.get("technicals") or {}
    price, s200 = t.get("last_close"), t.get("sma200")
    if price is None or s200 is None:
        return None
    above = price > s200
    weekly = t.get("higher_timeframe_trend")
    if above and weekly == "Uptrend":
        return _v("Trend Following", "bullish", 45, "above 200DMA + weekly uptrend")
    if not above and weekly == "Downtrend":
        return _v("Trend Following", "bearish", -45, "below 200DMA + weekly downtrend")
    return _v("Trend Following", "bullish" if above else "bearish",
              20 if above else -20, f"{'above' if above else 'below'} 200DMA, weekly mixed")


def bollinger_breakout(ctx) -> dict | None:
    t = ctx.get("technicals") or {}
    bb, price = t.get("bollinger"), t.get("last_close")
    if not bb or price is None:
        return None
    if price > bb["upper"]:
        return _v("Bollinger Breakout", "bullish", 30, "close above upper band")
    if price < bb["lower"]:
        return _v("Bollinger Breakout", "bearish", -30, "close below lower band")
    return None


def volume_surge(ctx) -> dict | None:
    """Unusual volume, direction taken from MACD momentum as confirmation."""
    t = ctx.get("technicals") or {}
    vol, avg = t.get("last_volume"), t.get("avg_volume_20d")
    if not vol or not avg or vol < 2 * avg:
        return None
    macd = t.get("macd")
    bullish = bool(macd and macd["histogram"] > 0)
    return _v("Volume Surge", "bullish" if bullish else "bearish",
              25 if bullish else -25, f"volume {vol/avg:.1f}× 20d avg")


def value_quality(ctx) -> dict | None:
    """Cheap-and-growing screen from fundamentals."""
    f = ctx.get("fundamentals") or {}
    pe = f.get("pe_ttm")
    growth = f.get("rev_yoy")
    if pe is None or growth is None:
        return None
    if 0 < pe < 20 and growth > 0.10:
        return _v("Value + Quality", "bullish", 35, f"P/E {pe:.1f}, rev +{growth:.0%}")
    if pe > 40 and growth < 0.05:
        return _v("Value + Quality", "bearish", -25, f"P/E {pe:.1f}, rev +{growth:.0%} (rich, slow)")
    return None


STRATEGIES = [ma_crossover, rsi_reversion, macd_momentum, trend_following,
              bollinger_breakout, volume_surge, value_quality]


def run_strategies(ctx: dict) -> list[dict]:
    """Every strategy that fires for one ticker's context."""
    return [v for v in (strat(ctx) for strat in STRATEGIES) if v]


def panel(tickers, technicals: dict, fundamentals: dict | None = None,
          composites: dict | None = None) -> dict:
    """{ticker: {verdicts, net_score, bull, bear}} — the compact matrix the
    analyst narrates. net_score is the mean strategy score (a quick tilt),
    NOT a fitted model — the lens interprets it, it doesn't invent it."""
    fundamentals, composites = fundamentals or {}, composites or {}
    out = {}
    for t in tickers:
        ctx = {"technicals": technicals.get(t), "fundamentals": fundamentals.get(t),
               "composite": composites.get(t)}
        verdicts = run_strategies(ctx)
        if not verdicts:
            continue
        scores = [v["score"] for v in verdicts]
        out[t] = {
            "verdicts": verdicts,
            "net_score": round(sum(scores) / len(scores), 1),
            "bull": sum(1 for v in verdicts if v["stance"] == "bullish"),
            "bear": sum(1 for v in verdicts if v["stance"] == "bearish"),
        }
    return out


if __name__ == "__main__":
    snap = {"sma50": 110, "sma200": 100, "rsi14": 25, "last_close": 120,
            "macd": {"histogram": 0.5}, "higher_timeframe_trend": "Uptrend",
            "bollinger": {"upper": 118, "lower": 95}, "last_volume": 300,
            "avg_volume_20d": 100}
    p = panel(["X"], {"X": snap}, {"X": {"pe_ttm": 15, "rev_yoy": 0.2}})
    fired = {v["name"] for v in p["X"]["verdicts"]}
    assert {"MA Crossover", "RSI Reversion", "MACD Momentum", "Trend Following",
            "Bollinger Breakout", "Volume Surge", "Value + Quality"} <= fired, fired
    assert p["X"]["bull"] == 7 and p["X"]["net_score"] > 0
    print("strategies self-check OK:", p["X"]["net_score"], sorted(fired))
