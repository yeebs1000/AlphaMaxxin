"""Feature vector for the ML Alpha model — the SINGLE source of truth for
what the model sees, imported by both the offline trainer
(scripts/train_ml_alpha.py) and the inference path (data/ml_model.py). Keeping
one function here is the whole train/serve-skew defence: if the two computed
features differently, the model's live predictions would be garbage in a way no
test catches. Every feature is derived from the same indicator math the
technicals skill already ships (app/skills/technicals.py) — no reimplementation.

All features are scale-free ratios so one model generalises across tickers at
very different price levels. Missing inputs (not enough history for an SMA200,
etc.) come back as NaN; the model (HistGradientBoostingClassifier) consumes NaN
natively, so there is no imputation to get wrong.
"""
import numpy as np

from . import technicals as ti

# Fixed column order. The trainer saves this alongside the model; inference
# asserts the saved names match so a feature added here can never silently
# misalign against an old artifact.
FEATURE_NAMES = [
    "rsi14",
    "close_vs_sma50",
    "close_vs_sma200",
    "sma50_vs_sma200",
    "close_vs_ema20",
    "bb_position",
    "atr_pct",
    "macd_hist_pct",
    "ret_20d",
    "ret_60d",
    "ret_120d",
    "dist_52w_high",
    "realized_vol_20d",
    "vol_ratio_20d",
]

# Enough daily bars to make the slowest feature (52-week high / 6-month
# momentum) meaningful. Below this, feature_at() returns None rather than a
# mostly-NaN row.
MIN_BARS = 252


def _safe_ratio(a, b):
    """a/b - 1, or NaN if either side is missing or b is ~0."""
    if a is None or b is None or b == 0:
        return np.nan
    return a / b - 1.0


def feature_at(closes, highs, lows, volumes, i: int) -> dict | None:
    """Feature dict at bar index `i` (inclusive), computed from history up to
    and including `i` only — never peeks forward, so a training row at `i` uses
    exactly what inference would see live at that bar. Returns None if `i` has
    too little history behind it.

    ponytail: recomputes each indicator over closes[:i+1] per call → O(n) per
    bar, O(n²) over a full series. Fine for ~1.25k bars × ~30 tickers at train
    time; if the universe grows big enough to notice, switch to incremental
    (streaming) indicator updates.
    """
    if i < MIN_BARS - 1 or i >= len(closes):
        return None
    c = np.asarray(closes[: i + 1], dtype=float)
    h = np.asarray(highs[: i + 1], dtype=float)
    l = np.asarray(lows[: i + 1], dtype=float)
    v = np.asarray(volumes[: i + 1], dtype=float)
    last = float(c[-1])

    sma50, sma200 = ti.sma(c, 50), ti.sma(c, 200)
    ema20 = ti.ema(c, 20)
    bb = ti.bollinger_bands(c)
    atr14 = ti.atr(h, l, c)
    macd = ti.macd(c)
    avg_vol20 = ti.sma(v, 20)

    bb_pos = np.nan
    if bb and (bb["upper"] - bb["lower"]):
        bb_pos = (last - bb["lower"]) / (bb["upper"] - bb["lower"])

    return {
        "rsi14": ti.rsi(c) if ti.rsi(c) is not None else np.nan,
        "close_vs_sma50": _safe_ratio(last, sma50),
        "close_vs_sma200": _safe_ratio(last, sma200),
        "sma50_vs_sma200": _safe_ratio(sma50, sma200),
        "close_vs_ema20": _safe_ratio(last, ema20),
        "bb_position": bb_pos,
        "atr_pct": (atr14 / last) if (atr14 is not None and last) else np.nan,
        "macd_hist_pct": (macd["histogram"] / last) if (macd and last) else np.nan,
        "ret_20d": (last / float(c[-21]) - 1.0) if len(c) > 20 and c[-21] else np.nan,
        "ret_60d": (last / float(c[-61]) - 1.0) if len(c) > 60 and c[-61] else np.nan,
        "ret_120d": (last / float(c[-121]) - 1.0) if len(c) > 120 and c[-121] else np.nan,
        # how far below the trailing 52-week high (<=0; 0 = at new high)
        "dist_52w_high": (last / float(np.max(h[-252:])) - 1.0)
                         if len(h) >= 252 and np.max(h[-252:]) else np.nan,
        # 20-day realized volatility (std of daily returns)
        "realized_vol_20d": float(np.std(np.diff(c[-21:]) / c[-21:-1]))
                            if len(c) > 20 and np.all(c[-21:-1]) else np.nan,
        "vol_ratio_20d": (float(v[-1]) / avg_vol20) if avg_vol20 else np.nan,
    }


def to_row(features: dict) -> list[float]:
    """Feature dict → list in FEATURE_NAMES order (the model's expected shape)."""
    return [features.get(name, np.nan) for name in FEATURE_NAMES]


def feature_row(closes, highs, lows, volumes, i: int) -> list[float] | None:
    f = feature_at(closes, highs, lows, volumes, i)
    return to_row(f) if f is not None else None


if __name__ == "__main__":
    # Self-check: deterministic, right shape, look-ahead free. No network.
    rng = np.random.default_rng(0)
    n = 400
    closes = list(np.cumsum(rng.normal(0, 1, n)) + 100)
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    volumes = list(rng.integers(1_000, 5_000, n).astype(float))

    r1 = feature_row(closes, highs, lows, volumes, 300)
    r2 = feature_row(closes, highs, lows, volumes, 300)
    assert r1 == r2, "features must be deterministic"
    assert len(r1) == len(FEATURE_NAMES), "row width must match FEATURE_NAMES"
    assert feature_at(closes, highs, lows, volumes, 10) is None, "too little history → None"

    # Look-ahead check: feature at i must not change when future bars are altered.
    tampered = list(closes)
    tampered[350] = tampered[350] + 999
    r3 = feature_row(tampered, highs, lows, volumes, 300)
    assert r1 == r3, "feature at i=300 must not depend on bars after i"
    print("ml_features self-check OK:", dict(zip(FEATURE_NAMES, r1)))
