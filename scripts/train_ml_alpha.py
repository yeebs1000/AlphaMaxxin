"""Offline trainer for the ML Alpha lens.

Run this ONCE (and re-run to refresh) to produce the model artifact that flips
the "Machine Learning Alpha Extractor" lens from disabled to live:

    python scripts/train_ml_alpha.py

⚠️  THIS HITS THE NETWORK (downloads price history via yfinance). Per the
project's HARD RULE #1 it is therefore *never* imported by the test suite —
tests build a tiny synthetic model in-memory instead. Running this is the user's
call, exactly like triggering a live report.

What it does: downloads ~5y daily OHLCV for a fixed liquid-large-cap universe,
builds features with the SAME app.skills.ml_features.feature_at used at
inference (no train/serve skew), labels each bar by the sign of its forward
20-day return, validates with a time-series split, fits a gradient-boosting
classifier on all data, and saves {model, feature_names, metrics, importances}
to backend/app/models/ml_alpha_v1.joblib.
"""
import datetime
import sys
from pathlib import Path

import numpy as np

# Make app.* importable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from app.skills import ml_features as feat  # noqa: E402

# ponytail: fixed ~30-name liquid US large-cap universe + single 20-day horizon
# + default-ish HistGBM params — the smallest thing that yields a real, honest
# validated model. Upgrade paths when it matters: widen/rotate the universe,
# add multiple horizons, purged walk-forward CV, hyperparameter search.
UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "JPM", "V",
    "UNH", "HD", "PG", "MA", "COST", "XOM", "JNJ", "WMT", "KO", "PEP",
    "ORCL", "CRM", "AMD", "NFLX", "ADBE", "BAC", "DIS", "CSCO", "INTC", "QCOM",
]
HORIZON_DAYS = 20
YEARS = 5
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


def _build_samples():
    """→ (dates, X, y) pooled across the universe. Each sample: features at bar
    i (history ≤ i only) labelled by sign of the forward HORIZON_DAYS return."""
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
            row = feat.feature_row(c, bars["highs"], bars["lows"], bars["volumes"], i)
            if row is None or any(x != x for x in row):  # drop rows with any NaN
                continue
            fwd = c[i + HORIZON_DAYS] / c[i] - 1.0
            dates.append(bars["dates"][i])
            rows.append(row)
            labels.append(1 if fwd > 0 else 0)
            made += 1
        print(f"  {ticker}: {made} samples")
    return np.array(dates), np.array(rows, dtype=float), np.array(labels, dtype=int)


def _validate(X, y):
    """Time-ordered out-of-sample validation. Returns mean accuracy + AUC over
    the splits — the honest skill estimate the lens is required to report."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.model_selection import TimeSeriesSplit

    accs, aucs = [], []
    for train_idx, test_idx in TimeSeriesSplit(n_splits=5).split(X):
        m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05,
                                           max_iter=300, random_state=0)
        m.fit(X[train_idx], y[train_idx])
        proba = m.predict_proba(X[test_idx])[:, list(m.classes_).index(1)]
        accs.append(accuracy_score(y[test_idx], (proba >= 0.5).astype(int)))
        if len(set(y[test_idx])) > 1:
            aucs.append(roc_auc_score(y[test_idx], proba))
    return {"accuracy": round(float(np.mean(accs)), 4),
            "auc": round(float(np.mean(aucs)), 4) if aucs else None,
            "n_splits": 5, "positive_rate": round(float(np.mean(y)), 4)}


def main():
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance

    print(f"Downloading {len(UNIVERSE)} tickers × ~{YEARS}y daily...")
    dates, X, y = _build_samples()
    if len(y) < 500:
        raise SystemExit(f"only {len(y)} samples — too few to train credibly")

    order = np.argsort(dates)  # chronological pooled panel
    X, y = X[order], y[order]
    print(f"Total {len(y)} samples, {y.mean():.1%} positive. Validating...")
    metrics = _validate(X, y)
    print(f"  OOS accuracy={metrics['accuracy']} auc={metrics['auc']}")

    # Fit the shipped model on ALL data; importances via permutation on a
    # held-out tail so they reflect out-of-sample behaviour, not train fit.
    model = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05,
                                           max_iter=300, random_state=0)
    split = int(len(y) * 0.8)
    model.fit(X[:split], y[:split])
    perm = permutation_importance(model, X[split:], y[split:], n_repeats=10,
                                  random_state=0)
    importances = {name: round(float(imp), 5)
                   for name, imp in zip(feat.FEATURE_NAMES, perm.importances_mean)}
    model.fit(X, y)  # final refit on everything for the artifact

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model,
        "feature_names": feat.FEATURE_NAMES,
        "trained_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "validation_metrics": metrics,
        "feature_importances": importances,
        "horizon_days": HORIZON_DAYS,
        "universe": UNIVERSE,
    }, ARTIFACT)
    print(f"Saved {ARTIFACT}")
    print("Restart the app — the ML Alpha lens will now show enabled.")


if __name__ == "__main__":
    main()
