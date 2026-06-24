"""
AlphaMaxxin — Real Technical Indicator Calculations
Computes RSI, MACD, Moving Averages, Bollinger Bands, ATR, and a volume
profile from real OHLCV bars, so the Technical Analysis Agent gets actual
numbers in its prompt context instead of inventing plausible-sounding ones.

Data source: moomoo OpenD daily/weekly K-line when reachable (regular-session
bars only), falling back to Yahoo Finance's chart API (same shape used by
gui.py's Historical Chart tab) when moomoo isn't available.

VOLUME vs TURNOVER: every value pulled or computed here is share-count
VOLUME. Turnover (price x volume, a dollar/value metric) is computed
separately and labelled separately wherever both are reported — they are
never summed or substituted for one another.

PRE/REGULAR/AFTER-HOURS VOLUME: only regular-session daily (or weekly) bars
are used. Both moomoo's K-line and Yahoo's chart `volume` field are
regular-session aggregates per bar; neither pre-market nor after-hours
volume is fetched or folded into any total here.
"""
import json
import urllib.parse
import urllib.request

import numpy as np

_YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


# ---------------------------------------------------------------------------
# OHLCV fetch
# ---------------------------------------------------------------------------
def fetch_ohlcv_yahoo(ticker: str, interval: str = "1d", range_: str = "1y") -> dict | None:
    """Regular-session OHLCV bars from Yahoo Finance's chart API. Returns
    {"closes","highs","lows","volumes"} as same-length lists (gaps dropped),
    or None on failure."""
    try:
        q = urllib.parse.quote(ticker)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?range={range_}&interval={interval}"
        req = urllib.request.Request(url, headers=_YAHOO_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        result = data["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        closes, highs, lows, volumes = quote["close"], quote["high"], quote["low"], quote["volume"]
        rows = [
            (c, h, l, v) for c, h, l, v in zip(closes, highs, lows, volumes)
            if c is not None and h is not None and l is not None and v is not None
        ]
        if len(rows) < 5:
            return None
        closes, highs, lows, volumes = (list(col) for col in zip(*rows))
        return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}
    except Exception:
        return None


def fetch_ohlcv_moomoo(ticker: str, ktype: str = "K_DAY", max_count: int = 260) -> dict | None:
    """Regular-session OHLCV bars via moomoo's history K-line API. Returns
    the same shape as fetch_ohlcv_yahoo, or None if moomoo-api isn't
    installed/reachable. moomoo's K-line `volume`/`turnover` columns are
    per-bar regular-session aggregates -- this never touches snapshot-only
    fields like pre/after-hours volume."""
    try:
        from moomoo_client import get_moomoo_kline
    except ImportError:
        return None
    rows = get_moomoo_kline(ticker, ktype=ktype, max_count=max_count)
    if not rows:
        return None
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    volumes = [r["volume"] for r in rows]
    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}


def fetch_ohlcv(ticker: str, interval: str = "1d", range_: str = "1y") -> dict | None:
    """Prefers live moomoo K-line; falls back to Yahoo Finance."""
    ktype = "K_WEEK" if interval == "1wk" else "K_DAY"
    bars = fetch_ohlcv_moomoo(ticker, ktype=ktype)
    if bars:
        return bars
    return fetch_ohlcv_yahoo(ticker, interval=interval, range_=range_)


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
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
    return {"macd": float(macd_line[-1]), "signal": float(signal_series[-1]), "histogram": float(histogram)}


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


def volume_profile(highs, lows, closes, volumes, num_bins: int = 24, value_area_pct: float = 0.70) -> dict | None:
    """Volume-by-price histogram built from share-count VOLUME only (never
    turnover). Returns the Point of Control (price level with the most
    volume traded) and the Value Area High/Low bounding `value_area_pct` of
    total volume -- i.e. where market participants' positions are actually
    concentrated, for grounding realistic target-price zones."""
    highs, lows, closes, volumes = (np.asarray(x, dtype=float) for x in (highs, lows, closes, volumes))
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


# ---------------------------------------------------------------------------
# Snapshot — what the agent actually consumes
# ---------------------------------------------------------------------------
def get_technical_snapshot(ticker: str, higher_timeframe: str = "1wk") -> dict | None:
    """Full real-data technical snapshot for one ticker: daily-bar indicators
    plus a higher-timeframe (default weekly) trend read. Returns None if no
    usable OHLCV data could be fetched from either moomoo or Yahoo Finance."""
    daily = fetch_ohlcv(ticker, interval="1d", range_="1y")
    if not daily:
        return None
    closes, highs, lows, volumes = daily["closes"], daily["highs"], daily["lows"], daily["volumes"]

    higher = fetch_ohlcv(ticker, interval=higher_timeframe, range_="2y")
    higher_trend = "Data unavailable"
    if higher and len(higher["closes"]) >= 10:
        h_closes = higher["closes"]
        h_sma10 = sma(h_closes, 10)
        h_sma30 = sma(h_closes, min(30, len(h_closes)))
        if h_sma10 is not None and h_sma30 is not None:
            higher_trend = "Uptrend" if h_sma10 > h_sma30 else "Downtrend" if h_sma10 < h_sma30 else "Flat"

    macd_vals = macd(closes)
    bb_vals = bollinger_bands(closes)
    vp_vals = volume_profile(highs, lows, closes, volumes)
    atr_val = atr(highs, lows, closes)
    last_volume = float(volumes[-1])
    last_turnover = float(closes[-1]) * last_volume  # price x volume -- a value metric, distinct from volume
    avg_volume_20d = sma(volumes, 20)

    return {
        "ticker": ticker,
        "last_close": float(closes[-1]),
        "ema20": ema(closes, 20),
        "sma50": sma(closes, 50),
        "sma200": sma(closes, 200),
        "rsi14": rsi(closes),
        "macd": macd_vals,
        "bollinger": bb_vals,
        "atr14": atr_val,
        "volume_profile": vp_vals,
        "last_volume": last_volume,
        "avg_volume_20d": avg_volume_20d,
        "last_turnover": last_turnover,
        "higher_timeframe_label": higher_timeframe,
        "higher_timeframe_trend": higher_trend,
        "bars_used": len(closes),
    }


def format_technical_context(snap: dict) -> str:
    """Renders a snapshot into the markdown block injected into the
    Technical Analysis Agent's prompt context."""
    if not snap:
        return ""

    def fmt(v, spec="{:.2f}"):
        return spec.format(v) if v is not None else "Data unavailable"

    macd_line = snap.get("macd")
    bb = snap.get("bollinger")
    vp = snap.get("volume_profile")

    macd_str = (
        f"line {fmt(macd_line['macd'], '{:.3f}')} | signal {fmt(macd_line['signal'], '{:.3f}')} | "
        f"histogram {fmt(macd_line['histogram'], '{:.3f}')}"
        if macd_line else "Data unavailable"
    )
    bb_str = (
        f"upper {fmt(bb['upper'])} | mid {fmt(bb['mid'])} | lower {fmt(bb['lower'])} | "
        f"width {fmt(bb['bandwidth_pct'], '{:.1f}')}%"
        if bb else "Data unavailable"
    )
    vp_str = (
        f"POC {fmt(vp['poc'])} | Value Area High {fmt(vp['vah'])} | Value Area Low {fmt(vp['val'])}"
        if vp else "Data unavailable"
    )

    return f"""
REAL COMPUTED TECHNICAL DATA for {snap['ticker']} ({snap['bars_used']} daily bars, regular session only):
- Last Close: {fmt(snap['last_close'])}
- Moving Averages: 20 EMA {fmt(snap['ema20'])} | 50 SMA {fmt(snap['sma50'])} | 200 SMA {fmt(snap['sma200'])}
- RSI(14): {fmt(snap['rsi14'], '{:.1f}')}
- MACD(12,26,9): {macd_str}
- Bollinger Bands(20, 2sd): {bb_str}
- ATR(14): {fmt(snap['atr14'])}
- Volume Profile (built from share VOLUME, NOT turnover): {vp_str}
- Latest session: Volume {snap['last_volume']:,.0f} shares | 20-day avg volume {fmt(snap['avg_volume_20d'], '{:,.0f}')} shares | Turnover (price x volume) ${snap['last_turnover']:,.0f}
  -- Volume and Turnover are different metrics; do not conflate them. Pre-market and after-hours volume are excluded from every figure above.
- Higher-Timeframe Trend ({snap['higher_timeframe_label']}): {snap['higher_timeframe_trend']}

Use these real values directly. Do not estimate, invent, or override any of the figures above.
"""
