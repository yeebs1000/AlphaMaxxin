"""Candlestick pattern detection — the classic reversal formations, hand-rolled
in pure Python (TA-Lib's Windows install pain isn't worth 8 patterns). Standard
textbook definitions; each detector looks at the LAST bar(s) of the supplied
OHLC arrays and returns pattern names. Context (after-decline / after-advance)
uses the 5-bar return before the pattern, per convention.

VALIDATION RESULT (2026-07 backtest, 52k events, 120 tickers, 10y, 60d
horizon): these patterns carry NO tradable directional edge — bullish set
+0.15% vs baseline (noise), bearish set +0.93% i.e. WRONG-signed (patterns
after advances are momentum markers, not reversal signals, at 60 days). They
ship as DESCRIPTIVE CONTEXT in the technicals snapshot only, never as a
strategy verdict. Re-test at shorter horizons before promoting them.
"""

# Body must be at least this fraction of the bar's range to count as a "real"
# body; below a tenth it's a doji-class bar.
_DOJI_BODY_FRAC = 0.10
_SHADOW_BODY_RATIO = 2.0   # hammer/shooting star: shadow ≥ 2× body
_TREND_BARS = 5            # lookback defining "after decline/advance"


def _bar(opens, closes, highs, lows, i):
    return {"open": opens[i], "close": closes[i], "high": highs[i], "low": lows[i],
            "body": abs(closes[i] - opens[i]), "range": highs[i] - lows[i],
            "up": closes[i] > opens[i]}


def _prior_trend(closes, i) -> str:
    """'down' | 'up' | 'flat' over the _TREND_BARS bars before bar i."""
    if i < _TREND_BARS:
        return "flat"
    then = closes[i - _TREND_BARS]
    if not then:
        return "flat"
    chg = (closes[i] - then) / then
    return "down" if chg < -0.02 else "up" if chg > 0.02 else "flat"


def detect(opens, closes, highs, lows) -> list[str]:
    """Patterns present at the LAST bar. Empty when opens are unavailable
    (older cached bars / providers without opens) or history is too short."""
    if not opens or len(opens) != len(closes) or len(closes) < _TREND_BARS + 3:
        return []
    i = len(closes) - 1
    cur = _bar(opens, closes, highs, lows, i)
    prev = _bar(opens, closes, highs, lows, i - 1)
    trend = _prior_trend(closes, i - 1)  # trend INTO the pattern
    found = []

    if cur["range"] > 0 and cur["body"] < _DOJI_BODY_FRAC * cur["range"]:
        found.append("doji")

    # Engulfing: opposite-color body strictly containing the previous body.
    if (cur["up"] and not prev["up"]
            and cur["open"] <= prev["close"] and cur["close"] >= prev["open"]
            and cur["body"] > prev["body"]):
        found.append("bullish_engulfing")
    if (not cur["up"] and prev["up"]
            and cur["open"] >= prev["close"] and cur["close"] <= prev["open"]
            and cur["body"] > prev["body"]):
        found.append("bearish_engulfing")

    # Hammer / shooting star: long single shadow after a trend.
    if cur["body"] > 0:
        lower_shadow = min(cur["open"], cur["close"]) - cur["low"]
        upper_shadow = cur["high"] - max(cur["open"], cur["close"])
        if (trend == "down" and lower_shadow >= _SHADOW_BODY_RATIO * cur["body"]
                and upper_shadow <= cur["body"]):
            found.append("hammer")
        if (trend == "up" and upper_shadow >= _SHADOW_BODY_RATIO * cur["body"]
                and lower_shadow <= cur["body"]):
            found.append("shooting_star")

    # Harami: small body inside the previous large opposite body.
    if (prev["body"] > 0 and cur["body"] < prev["body"] * 0.5
            and max(cur["open"], cur["close"]) <= max(prev["open"], prev["close"])
            and min(cur["open"], cur["close"]) >= min(prev["open"], prev["close"])):
        found.append("bullish_harami" if not prev["up"] else "bearish_harami")

    # Morning / evening star: 3-bar reversal (big body, small body, big
    # opposite body closing past the first bar's midpoint).
    if i >= 2:
        first = _bar(opens, closes, highs, lows, i - 2)
        mid_small = prev["body"] < first["body"] * 0.5
        if (not first["up"] and mid_small and cur["up"] and first["body"] > 0
                and cur["close"] > (first["open"] + first["close"]) / 2
                and _prior_trend(closes, i - 2) == "down"):
            found.append("morning_star")
        if (first["up"] and mid_small and not cur["up"] and first["body"] > 0
                and cur["close"] < (first["open"] + first["close"]) / 2
                and _prior_trend(closes, i - 2) == "up"):
            found.append("evening_star")

    return found


BULLISH = {"bullish_engulfing", "hammer", "bullish_harami", "morning_star"}
BEARISH = {"bearish_engulfing", "shooting_star", "bearish_harami", "evening_star"}
