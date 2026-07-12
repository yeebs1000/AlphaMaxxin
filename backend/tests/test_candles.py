"""Candlestick detectors: textbook fixtures per pattern, graceful no-opens."""
from app.skills import candles


def _series(bars):
    """bars: list of (open, high, low, close) → parallel arrays."""
    opens = [b[0] for b in bars]
    highs = [b[1] for b in bars]
    lows = [b[2] for b in bars]
    closes = [b[3] for b in bars]
    return opens, closes, highs, lows


def _downtrend(n=7, start=110.0):
    """Falling red candles: close < open, stepping down > 2%/bar overall."""
    return [(start - i * 2, start - i * 2 + 0.4, start - i * 2 - 2.4,
             start - i * 2 - 2.0) for i in range(n)]


def _uptrend(n=7, start=100.0):
    return [(start + i * 2, start + i * 2 + 2.4, start + i * 2 - 0.4,
             start + i * 2 + 2.0) for i in range(n)]


def test_no_opens_or_short_history_is_empty():
    assert candles.detect(None, [1, 2, 3], [1, 2, 3], [1, 2, 3]) == []
    o, c, h, l = _series(_downtrend(3))
    assert candles.detect(o, c, h, l) == []


def test_bullish_engulfing_after_decline():
    # Prior red body is 98→96; green bar opens below 96, closes above 98.
    bars = _downtrend() + [(95.9, 98.8, 95.5, 98.5)]
    o, c, h, l = _series(bars)
    assert "bullish_engulfing" in candles.detect(o, c, h, l)


def test_bearish_engulfing_after_advance():
    # Prior green body is 112→114; red bar opens above 114, closes below 112.
    bars = _uptrend() + [(114.2, 114.5, 111.5, 111.8)]
    o, c, h, l = _series(bars)
    assert "bearish_engulfing" in candles.detect(o, c, h, l)


def test_hammer_needs_downtrend_and_long_lower_shadow():
    hammer = (100.0, 100.6, 96.0, 100.5)  # body .5 at top, lower shadow 4
    o, c, h, l = _series(_downtrend() + [hammer])
    assert "hammer" in candles.detect(o, c, h, l)
    o, c, h, l = _series(_uptrend() + [hammer])  # same bar, wrong context
    assert "hammer" not in candles.detect(o, c, h, l)


def test_shooting_star_after_advance():
    star = (112.0, 116.5, 111.9, 112.4)  # body .4 at bottom, upper shadow ~4
    o, c, h, l = _series(_uptrend() + [star])
    assert "shooting_star" in candles.detect(o, c, h, l)


def test_doji_tiny_body():
    bars = _uptrend() + [(112.0, 114.0, 110.0, 112.05)]  # body .05 of range 4
    o, c, h, l = _series(bars)
    assert "doji" in candles.detect(o, c, h, l)


def test_morning_star_three_bar_reversal():
    bars = _downtrend() + [
        (100.0, 100.2, 95.8, 96.0),    # big red
        (95.8, 96.3, 95.3, 95.9),      # small body
        (96.2, 99.6, 96.0, 99.5),      # big green closing above first midpoint (98)
    ]
    o, c, h, l = _series(bars)
    assert "morning_star" in candles.detect(o, c, h, l)


def test_harami_small_inside_body():
    bars = _uptrend() + [(110.0, 114.2, 109.8, 114.0),   # big green
                         (112.5, 112.9, 111.9, 112.0)]   # small red inside
    o, c, h, l = _series(bars)
    assert "bearish_harami" in candles.detect(o, c, h, l)
