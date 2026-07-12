"""Technical indicators — math ported verbatim from technical_indicators.py
(same algorithms, so v1 outputs serve as golden test values). Pure functions:
OHLCV dicts in, JSON-serializable snapshot out. No network.
"""
import numpy as np

from . import candles


def sma(values, period: int) -> float | None:
    values = np.asarray(values, dtype=float)
    if len(values) < period:
        return None
    return float(np.mean(values[-period:]))


def _ema_series(values, period: int):
    values = np.asarray(values, dtype=float)
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1)
    ema_val = float(np.mean(values[:period]))
    out = [ema_val]
    for v in values[period:]:
        ema_val = alpha * v + (1 - alpha) * ema_val
        out.append(ema_val)
    return out


def ema(values, period: int) -> float | None:
    series = _ema_series(values, period)
    return series[-1] if series else None


def rsi(closes, period: int = 14) -> float | None:
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def macd(closes, fast: int = 12, slow: int = 26, signal: int = 9) -> dict | None:
    if len(closes) < slow + signal:
        return None
    ema_fast_series = _ema_series(closes, fast)
    ema_slow_series = _ema_series(closes, slow)
    if not ema_fast_series or not ema_slow_series:
        return None
    n = min(len(ema_fast_series), len(ema_slow_series))
    macd_line = (np.array(ema_fast_series[-n:]) - np.array(ema_slow_series[-n:])).tolist()
    signal_series = _ema_series(macd_line, signal)
    if not signal_series:
        return None
    histogram = macd_line[-1] - signal_series[-1]
    return {"macd": float(macd_line[-1]), "signal": float(signal_series[-1]),
            "histogram": float(histogram)}


def bollinger_bands(closes, period: int = 20, num_std: float = 2.0) -> dict | None:
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = float(np.mean(window))
    std = float(np.std(window))
    upper, lower = mid + num_std * std, mid - num_std * std
    bandwidth_pct = ((upper - lower) / mid) * 100 if mid else 0.0
    return {"upper": upper, "mid": mid, "lower": lower, "bandwidth_pct": bandwidth_pct}


def atr(highs, lows, closes, period: int = 14) -> float | None:
    highs, lows, closes = (np.asarray(x, dtype=float) for x in (highs, lows, closes))
    if len(closes) < period + 1:
        return None
    prev_close = closes[:-1]
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - prev_close), np.abs(lows[1:] - prev_close)),
    )
    return float(np.mean(tr[-period:]))


def volume_profile(highs, lows, closes, volumes, num_bins: int = 24,
                   value_area_pct: float = 0.70) -> dict | None:
    """Volume-by-price from share-count VOLUME only (never turnover): Point of
    Control + Value Area High/Low bounding value_area_pct of total volume."""
    highs, lows, closes, volumes = (np.asarray(x, dtype=float)
                                    for x in (highs, lows, closes, volumes))
    if len(closes) == 0 or np.sum(volumes) <= 0:
        return None
    typical = (highs + lows + closes) / 3.0
    lo, hi = float(np.min(lows)), float(np.max(highs))
    if hi <= lo:
        return None
    bins = np.linspace(lo, hi, num_bins + 1)
    bin_volume = np.zeros(num_bins)
    bin_idx = np.clip(np.digitize(typical, bins) - 1, 0, num_bins - 1)
    for idx, vol in zip(bin_idx, volumes):
        bin_volume[idx] += vol
    poc_bin = int(np.argmax(bin_volume))
    poc_price = (bins[poc_bin] + bins[poc_bin + 1]) / 2.0
    total_volume = float(np.sum(bin_volume))
    order = np.argsort(bin_volume)[::-1]
    target = total_volume * value_area_pct
    included, running = [], 0.0
    for idx in order:
        included.append(idx)
        running += bin_volume[idx]
        if running >= target:
            break
    lo_idx, hi_idx = min(included), max(included)
    return {"poc": float(poc_price), "vah": float(bins[hi_idx + 1]), "val": float(bins[lo_idx])}


def compute_snapshot(ticker: str, daily: dict, higher: dict | None = None,
                     higher_label: str = "1wk") -> dict | None:
    """Full technical snapshot for one ticker from pre-fetched OHLCV dicts
    ({"closes","highs","lows","volumes"}). Same fields as v1's
    get_technical_snapshot plus a mechanical signal block."""
    if not daily or len(daily.get("closes", [])) == 0:
        return None
    closes, highs = daily["closes"], daily["highs"]
    lows, volumes = daily["lows"], daily["volumes"]

    higher_trend = "Data unavailable"
    if higher and len(higher.get("closes", [])) >= 10:
        h_closes = higher["closes"]
        h_sma10 = sma(h_closes, 10)
        h_sma30 = sma(h_closes, min(30, len(h_closes)))
        if h_sma10 is not None and h_sma30 is not None:
            higher_trend = ("Uptrend" if h_sma10 > h_sma30
                            else "Downtrend" if h_sma10 < h_sma30 else "Flat")

    snap = {
        "ticker": ticker,
        "last_close": float(closes[-1]),
        "ema20": ema(closes, 20),
        "sma50": sma(closes, 50),
        "sma200": sma(closes, 200),
        "rsi14": rsi(closes),
        "macd": macd(closes),
        "bollinger": bollinger_bands(closes),
        "atr14": atr(highs, lows, closes),
        "volume_profile": volume_profile(highs, lows, closes, volumes),
        "last_volume": float(volumes[-1]),
        "avg_volume_20d": sma(volumes, 20),
        "last_turnover": float(closes[-1]) * float(volumes[-1]),
        "high_20": float(np.max(highs[-20:])) if len(highs) >= 20 else None,
        "high_252": float(np.max(highs[-252:])) if len(highs) >= 252 else None,
        # Empty when the bars carry no opens (older cache entries, some
        # fallback providers) — detectors need real opens, never guesses.
        "candle_patterns": candles.detect(daily.get("opens"), closes, highs, lows),
        "higher_timeframe_label": higher_label,
        "higher_timeframe_trend": higher_trend,
        "bars_used": len(closes),
    }
    snap["signal"] = _mechanical_signal(snap)
    return snap


def _mechanical_signal(snap: dict) -> dict:
    """Transparent −100..+100 score from the computed indicators, with the
    contributing reasons spelled out. Free — no LLM involved.

    Weights are calibrated to the 2026-07 event-study backtest (52k events,
    120 tickers, 10y — scripts/backtest_signals.py): oversold mean-reversion
    carried the only large edge (+2.9%/60d), the death cross was the best
    bearish flag, trend/MACD contributions measured weak-to-wrong-signed at
    60d and previously over-dominated the score (extreme-bullish quintile
    underperformed the middle). Re-run the backtest after changing these."""
    score = 0
    reasons = []
    last = snap["last_close"]

    rsi14 = snap.get("rsi14")
    if rsi14 is not None:
        if rsi14 < 30:
            score += 30; reasons.append(f"RSI {rsi14:.0f} oversold (+30)")
        elif rsi14 < 45:
            score += 10; reasons.append(f"RSI {rsi14:.0f} below neutral (+10)")
        elif rsi14 > 70:
            score -= 10; reasons.append(f"RSI {rsi14:.0f} overbought (-10)")
        elif rsi14 > 60:
            score -= 5; reasons.append(f"RSI {rsi14:.0f} elevated (-5)")

    sma50, sma200 = snap.get("sma50"), snap.get("sma200")
    if sma50 is not None:
        if last > sma50:
            score += 10; reasons.append("above 50-day SMA (+10)")
        else:
            score -= 10; reasons.append("below 50-day SMA (-10)")
    if sma200 is not None:
        if last > sma200:
            score += 10; reasons.append("above 200-day SMA (+10)")
        else:
            score -= 10; reasons.append("below 200-day SMA (-10)")
    if sma50 is not None and sma200 is not None:
        if sma50 > sma200:
            score += 10; reasons.append("golden alignment 50>200 (+10)")
        else:
            score -= 10; reasons.append("dead alignment 50<200 (-10)")

    macd_vals = snap.get("macd")
    if macd_vals:
        if macd_vals["histogram"] > 0:
            score += 5; reasons.append("MACD histogram positive (+5)")
        else:
            score -= 5; reasons.append("MACD histogram negative (-5)")

    trend = snap.get("higher_timeframe_trend")
    if trend == "Uptrend":
        score += 10; reasons.append("weekly uptrend (+10)")
    elif trend == "Downtrend":
        score -= 10; reasons.append("weekly downtrend (-10)")

    # ponytail: known ceiling — the TOP score quintile still underperforms the
    # middle (~4.5% vs ~6.2% fwd 60d): max-score names are late-cycle by
    # construction, and an extended-trend interaction penalty was tried and
    # only flattened the useful mid-range ranking (see backtest history).
    # Treat very high scores as "strong but extended", and lean on the RSI
    # Reversion strategy (the one large measured edge) for fresh entries.

    score = max(-100, min(100, score))
    label = ("strong buy" if score >= 60 else "buy" if score >= 25
             else "strong sell" if score <= -60 else "sell" if score <= -25
             else "hold")
    return {"score": score, "label": label, "reasons": reasons}
