"""Offline trainer for the ML Alpha lens.

Run this ONCE (and re-run to refresh) to produce the model artifact that flips
the "Machine Learning Alpha Extractor" lens from disabled to live:

    python scripts/train_ml_alpha.py

⚠️  THIS HITS THE NETWORK (downloads price history via yfinance). Per the
project's HARD RULE #1 it is therefore *never* imported by the test suite —
tests build a tiny synthetic model in-memory instead. Running this is the user's
call, exactly like triggering a live report.

What it does: downloads ~10y daily OHLCV for a ~120-name multi-region universe,
builds features with the SAME app.skills.ml_features.feature_at used at
inference (no train/serve skew), labels each bar by whether the stock BEATS
the S&P 500 over the forward HORIZON_DAYS window (relative return, not raw
direction — a 60-day up move that trails the market isn't the signal we want),
dropping near-zero relative moves as unlabelable noise. Validates with a
time-series split, fits a gradient-boosting classifier on all data, and saves
{model, feature_names, metrics, importances} to
backend/app/models/ml_alpha_v1.joblib.

Why relative-to-benchmark instead of raw direction: a first pass trained on
raw 20-day direction came back at AUC ~0.51 (a coin flip) — the only features
with any real signal were the momentum ones (ret_60d/120d, sma50_vs_sma200),
and raw direction is dominated by the market's own drift (56% of days are
"up" regardless of the stock). Relative return isolates stock-specific
momentum from beta, and the longer 60-day horizon gives that momentum more
room to matter than a noisy 20-day window.

This pass ALSO adds macro context (CPI/PPI/curve/NFP/Fed-dot-plot) as features,
via the SAME app.skills.ml_macro_features.from_macro_snapshot used at live
inference. Point-in-time correctness: every FRED observation is only treated
as "known" LAG_DAYS after its reference date (a conservative uniform buffer,
not real per-series publication timing) — otherwise a historical training
sample would see a CPI print before it was actually public, an obvious
lookahead leak. Live serving needs no such lag (today's live snapshot only
ever contains already-public data).
"""
import bisect
import datetime
import sys
from pathlib import Path

import numpy as np

# Make app.* importable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from app.skills import ml_features as feat  # noqa: E402
from app.skills import ml_macro_features as macro_feat  # noqa: E402
from app.skills import macro as macro_skill  # noqa: E402

from app.skills.screener import CANDIDATE_LISTS  # noqa: E402

# Comprehensive multi-region universe: a broad US large/mega-cap core PLUS the
# screener's curated US/SG/HK/JP/KR candidate lists, so the model learns from
# the same kinds of names it will score at inference across every market.
# ponytail: single 20-day horizon + one HistGBM config with early stopping —
# still one honest validated model, just trained wider/longer. Upgrade paths:
# multiple horizons, purged walk-forward CV, hyperparameter search.
_US_CORE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "JPM", "V",
    "UNH", "HD", "PG", "MA", "COST", "XOM", "JNJ", "WMT", "KO", "PEP",
    "ORCL", "CRM", "AMD", "NFLX", "ADBE", "BAC", "DIS", "CSCO", "INTC", "QCOM",
    "TXN", "IBM", "GE", "CAT", "GS", "MS", "PFE", "MRK", "ABBV", "LLY",
    "TMO", "DHR", "ABT", "NKE", "MCD", "SBUX", "LOW", "UPS", "CVX", "COP",
    "BA", "HON", "UNP", "T", "VZ", "CMCSA", "PM", "LIN", "NEE", "AMAT",
]
UNIVERSE = sorted(set(_US_CORE) | {t for lst in CANDIDATE_LISTS.values() for t in lst})
HORIZON_DAYS = 60
YEARS = 10
BENCHMARK = "^GSPC"
# Relative moves smaller than this are noise, not a callable "beats/lags the
# market" signal — dropped rather than forced into an arbitrary up/down label.
DEAD_ZONE = 0.02
# ponytail: one uniform lag for every macro series, not each one's real
# publication delay (NFP ~1wk, CPI/PPI ~2-3wk, SEP same-day) — a deliberately
# conservative margin-of-safety, not per-series precision. Upgrade path: real
# ALFRED vintage data if this ever needs to be exact.
MACRO_LAG_DAYS = 45
# Raw FRED series IDs needed to reconstruct a compute_macro()-shaped snapshot
# at each historical sample date.
_MACRO_SERIES_IDS = ["FEDFUNDS", "DGS2", "DGS10", "CPIAUCSL", "CPILFESL",
                    "PPIFIS", "PPICOR", "PAYEMS", "UNRATE", "FEDTARMD"]
COMBINED_FEATURE_NAMES = feat.FEATURE_NAMES + macro_feat.MACRO_FEATURE_NAMES
ARTIFACT = _REPO_ROOT / "backend" / "app" / "models" / "ml_alpha_v1.joblib"


def _download(ticker: str):
    import yfinance as yf
    end = datetime.date.today()
    start = end - datetime.timedelta(days=int(YEARS * 365.25) + 30)
    df = yf.download(ticker, start=start.isoformat(), end=end.isoformat(),
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        return None
    # yfinance can return single- or multi-index columns depending on version.
    col = lambda name: (df[name][ticker] if isinstance(df.columns, __import__("pandas").MultiIndex)
                        else df[name])
    return {
        "closes": [float(x) for x in col("Close").tolist()],
        "highs": [float(x) for x in col("High").tolist()],
        "lows": [float(x) for x in col("Low").tolist()],
        "volumes": [float(x) for x in col("Volume").tolist()],
        "dates": [d.to_pydatetime() for d in df.index],
    }


def _spx_fwd_return(spx_dates, spx_closes, date, horizon: int) -> float | None:
    """Forward HORIZON_DAYS return of the benchmark as of `date`, aligned by
    nearest trading date (HK/JP/KR/SG calendars don't match the US exactly, so
    an exact date match would drop most non-US samples)."""
    i = bisect.bisect_left(spx_dates, date)
    if i >= len(spx_dates) or i + horizon >= len(spx_dates):
        return None
    return spx_closes[i + horizon] / spx_closes[i] - 1.0


def _fetch_macro_series(fred) -> dict:
    """Every raw FRED series needed for the macro panel, fetched once. limit is
    generously large (default 400 covers only ~1.6y of the DAILY series DGS2/
    DGS10 — nowhere near the ~10y+lag training window; the resulting all-NaN
    early history crashed HistGBM's binning on a fold with zero real values in
    that column). Harmless for the monthly/quarterly series, which simply
    return however many observations actually exist."""
    return {sid: fred.series(sid, limit=4000) for sid in _MACRO_SERIES_IDS}


def _lag_and_sort(series: dict | None, lag_days: int):
    """A FRED series' observations, each shifted `lag_days` forward (the date
    it becomes "known"), as a (dates, values) pair ready for bisect lookups."""
    if not series or not series.get("observations"):
        return [], []
    dates, values = [], []
    for obs in series["observations"]:
        d = datetime.date.fromisoformat(obs["date"]) + datetime.timedelta(days=lag_days)
        dates.append(d)
        values.append(obs["value"])
    return dates, values


def _asof_series(lagged_dates, lagged_values, as_of: datetime.date) -> dict | None:
    """A FRED-series-shaped dict containing only observations known as of
    `as_of` — fed straight into macro.py's OWN _yoy_pct/_change_over/_latest so
    the historical math is identical to the live path, not reimplemented."""
    idx = bisect.bisect_right(lagged_dates, as_of)
    if idx == 0:
        return None
    return {"observations": [{"date": "unused", "value": v} for v in lagged_values[:idx]]}


def _macro_snapshot_asof(macro_lagged: dict, as_of: datetime.date) -> dict:
    """Reconstruct a compute_macro()-shaped dict as of a historical date, using
    ONLY data that would have been public by then (per MACRO_LAG_DAYS). Reuses
    macro.py's own _latest/_yoy_pct/_change_over — same functions the live app
    calls, so training and serving compute macro fields identically."""
    def s(sid):
        return _asof_series(*macro_lagged[sid], as_of)

    fed_funds = macro_skill._latest(s("FEDFUNDS"))
    ust2y = macro_skill._latest(s("DGS2"))
    ust10y = macro_skill._latest(s("DGS10"))
    dot_next_year = macro_skill._latest(s("FEDTARMD"))
    curve_2s10s = (ust10y - ust2y) if ust10y is not None and ust2y is not None else None
    gap = (ust2y - dot_next_year) if ust2y is not None and dot_next_year is not None else None
    return {
        "inflation": {"cpi_yoy": macro_skill._yoy_pct(s("CPIAUCSL")),
                     "core_cpi_yoy": macro_skill._yoy_pct(s("CPILFESL"))},
        "producer_prices": {"ppi_yoy": macro_skill._yoy_pct(s("PPIFIS")),
                           "core_ppi_yoy": macro_skill._yoy_pct(s("PPICOR"))},
        "rates": {"curve_2s10s": curve_2s10s, "fed_funds": fed_funds},
        "labor": {"nonfarm_payrolls_change_k": macro_skill._change_over(s("PAYEMS"), 1),
                 "unemployment": macro_skill._latest(s("UNRATE"))},
        "fed_dot_plot": {"market_vs_fed_gap": gap},
    }


def _build_samples():
    """→ (dates, X, y) pooled across the universe. Each sample: technical
    features at bar i (history ≤ i only) + point-in-time-safe macro features
    as of that date, labelled by whether the stock's forward HORIZON_DAYS
    return beats the benchmark's, by more than DEAD_ZONE either way."""
    from app.data.base import DiskTTLCache
    from app.data.fred import FredProvider

    print(f"Downloading benchmark {BENCHMARK} for relative labelling...")
    spx = _download(BENCHMARK)
    spx_dates = [d.date() for d in spx["dates"]]
    spx_closes = spx["closes"]

    print("Downloading macro series (FRED) for point-in-time features...")
    fred = FredProvider(DiskTTLCache())
    raw_macro = _fetch_macro_series(fred)
    macro_lagged = {sid: _lag_and_sort(series, MACRO_LAG_DAYS)
                    for sid, series in raw_macro.items()}

    dates, rows, labels = [], [], []
    for ticker in UNIVERSE:
        bars = _download(ticker)
        if not bars:
            print(f"  {ticker}: no data, skipped")
            continue
        c = bars["closes"]
        n = len(c)
        made = 0
        for i in range(feat.MIN_BARS - 1, n - HORIZON_DAYS):
            technical = feat.feature_at(c, bars["highs"], bars["lows"], bars["volumes"], i)
            if technical is None or any(v != v for v in technical.values()):
                continue  # drop rows with any NaN technical feature
            fwd_stock = c[i + HORIZON_DAYS] / c[i] - 1.0
            sample_date = bars["dates"][i].date()
            fwd_spx = _spx_fwd_return(spx_dates, spx_closes, sample_date, HORIZON_DAYS)
            if fwd_spx is None:
                continue
            rel = fwd_stock - fwd_spx
            if abs(rel) < DEAD_ZONE:  # not a callable outperform/underperform
                continue
            macro_snapshot = _macro_snapshot_asof(macro_lagged, sample_date)
            combined = {**technical, **macro_feat.from_macro_snapshot(macro_snapshot)}
            row = [combined.get(name, np.nan) for name in COMBINED_FEATURE_NAMES]
            dates.append(bars["dates"][i])
            rows.append(row)
            labels.append(1 if rel > 0 else 0)
            made += 1
        print(f"  {ticker}: {made} samples")
    return np.array(dates), np.array(rows, dtype=float), np.array(labels, dtype=int)


def _new_model():
    """One shared model config: shallow trees, slow learning rate, L2 reg and
    early stopping — robust defaults for a wide, noisy financial panel."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(
        max_depth=4, learning_rate=0.03, max_iter=600, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.15, random_state=0)


def _validate(X, y):
    """Time-ordered out-of-sample validation. Returns mean accuracy + AUC over
    the splits — the honest skill estimate the lens is required to report."""
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.model_selection import TimeSeriesSplit

    accs, aucs = [], []
    for train_idx, test_idx in TimeSeriesSplit(n_splits=5).split(X):
        m = _new_model()
        m.fit(X[train_idx], y[train_idx])
        proba = m.predict_proba(X[test_idx])[:, list(m.classes_).index(1)]
        accs.append(accuracy_score(y[test_idx], (proba >= 0.5).astype(int)))
        if len(set(y[test_idx])) > 1:
            aucs.append(roc_auc_score(y[test_idx], proba))
    return {"accuracy": round(float(np.mean(accs)), 4),
            "auc": round(float(np.mean(aucs)), 4) if aucs else None,
            "n_splits": 5, "positive_rate": round(float(np.mean(y)), 4)}


def _drop_degenerate_columns(X, names: list[str]):
    """Drop any column with fewer than 2 distinct non-NaN values, checked BOTH
    globally AND within every TimeSeriesSplit(5) fold's train slice (the same
    split _validate uses) — a column can look fine globally (e.g. the Fed dot
    plot: 14 distinct values over the whole 10y panel) while still being 100%
    NaN in the earliest fold alone, because that data barely existed that far
    back. HistGradientBoostingClassifier's binning step crashes outright
    ('window shape cannot be larger than input array shape') on ANY fit call
    where a column is that degenerate — a global-only check missed this the
    first time. Reports what it drops so a silently-thin macro series doesn't
    go unnoticed."""
    from sklearn.model_selection import TimeSeriesSplit

    def n_unique(arr):
        return len(np.unique(arr[~np.isnan(arr)]))

    fold_train_idx = [train_idx for train_idx, _ in TimeSeriesSplit(n_splits=5).split(X)]
    keep_idx, kept_names = [], []
    for j, name in enumerate(names):
        col = X[:, j]
        global_n = n_unique(col)
        fold_ns = [n_unique(col[idx]) for idx in fold_train_idx]
        worst = min([global_n] + fold_ns)
        nan_frac = float(np.isnan(col).mean())
        print(f"  {name:20} n_unique={global_n:5d}  min_fold_n_unique={min(fold_ns):5d}"
              f"  nan_frac={nan_frac:.2%}"
              + ("  -> DROPPED (degenerate in a fold)" if worst < 2 else ""))
        if worst >= 2:
            keep_idx.append(j)
            kept_names.append(name)
    return X[:, keep_idx], kept_names


def main():
    import joblib
    from sklearn.inspection import permutation_importance

    print(f"Downloading {len(UNIVERSE)} tickers x ~{YEARS}y daily...")
    dates, X, y = _build_samples()
    if len(y) < 500:
        raise SystemExit(f"only {len(y)} samples — too few to train credibly")

    order = np.argsort(dates)  # chronological pooled panel
    X, y = X[order], y[order]
    print(f"Total {len(y)} samples, {y.mean():.1%} positive.")
    print("Feature diagnostics:")
    X, feature_names = _drop_degenerate_columns(X, COMBINED_FEATURE_NAMES)
    print("Validating...")
    metrics = _validate(X, y)
    print(f"  OOS accuracy={metrics['accuracy']} auc={metrics['auc']}")

    # Fit the shipped model on ALL data; importances via permutation on a
    # held-out tail so they reflect out-of-sample behaviour, not train fit.
    model = _new_model()
    split = int(len(y) * 0.8)
    model.fit(X[:split], y[:split])
    perm = permutation_importance(model, X[split:], y[split:], n_repeats=10,
                                  random_state=0)
    importances = {name: round(float(imp), 5)
                   for name, imp in zip(feature_names, perm.importances_mean)}
    model = _new_model()
    model.fit(X, y)  # final refit on everything for the artifact

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model,
        "feature_names": feature_names,
        "trained_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "validation_metrics": metrics,
        "feature_importances": importances,
        "horizon_days": HORIZON_DAYS,
        "universe": UNIVERSE,
        "label": f"beats {BENCHMARK} by >{DEAD_ZONE:.0%} over {HORIZON_DAYS}d",
    }, ARTIFACT)
    print(f"Saved {ARTIFACT}")
    print("Restart the app — the ML Alpha lens will now show enabled.")


if __name__ == "__main__":
    main()
