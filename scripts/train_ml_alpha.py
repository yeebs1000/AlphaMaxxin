"""Offline trainer for the ML Alpha lens.

Run this ONCE (and re-run to refresh) to produce the model artifact that flips
the "Machine Learning Alpha Extractor" lens from disabled to live:

    python scripts/train_ml_alpha.py

⚠️  THIS HITS THE NETWORK (yfinance + FRED). Per HARD RULE #1 it is therefore
not executed by the test suite — tests import its pure split helpers and use
synthetic samples. Running training is the user's call, like a live report.

Downloads ~10y daily OHLCV for a ~120-name multi-region universe, builds
technical features (app.skills.ml_features) and macro features
(app.skills.ml_macro_features) — the SAME functions live inference uses, no
train/serve skew — labels each bar by whether the stock beats the S&P 500 over
HORIZON_DAYS (relative return isolates stock-specific momentum from the
market's own drift; raw direction gave no edge, see git history), validates
with purged complete-date splits, and saves {model, feature_names, metrics,
importances} to backend/app/models/ml_alpha_v1.joblib.

FRED observations receive a conservative MACRO_LAG_DAYS publication lag.
These are nevertheless latest revised histories, not historical vintages;
this is NOT a fully point-in-time macro reconstruction. Validation groups
whole dates and purges actual label end dates before every test window.
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
from app.data.ml_model import VALIDATION_PROTOCOL, RESEARCH_LIMITATIONS  # noqa: E402

# Comprehensive multi-region universe: a broad US large/mega-cap core PLUS the
# screener's curated US/SG/HK/JP/KR candidate lists, so the model learns from
# the same kinds of names it will score at inference across every market.
# ponytail: one 60-session horizon and one HistGBM config; multiple horizons
# and parameter search require separate purged evaluation if ever added.
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
        "opens": [float(x) for x in col("Open").tolist()],
        "closes": [float(x) for x in col("Close").tolist()],
        "highs": [float(x) for x in col("High").tolist()],
        "lows": [float(x) for x in col("Low").tolist()],
        "volumes": [float(x) for x in col("Volume").tolist()],
        "dates": [d.to_pydatetime() for d in df.index],
    }


def _spx_fwd_return(spx_dates, spx_closes, date, end_date) -> tuple | None:
    """Benchmark return over the stock's calendar window, plus actual end date.

    The next US session is used at either endpoint when markets' calendars
    differ. That endpoint is carried into purging, rather than assuming every
    exchange's 60th session lands on the same date.
    """
    i = bisect.bisect_left(spx_dates, date)
    j = bisect.bisect_left(spx_dates, end_date)
    if i >= len(spx_dates) or j >= len(spx_dates) or j <= i or not spx_closes[i]:
        return None
    return spx_closes[j] / spx_closes[i] - 1.0, spx_dates[j]


def _fetch_macro_series(fred) -> dict:
    """Every raw FRED series needed for the macro panel, fetched once. A large
    limit matters for the DAILY series (DGS2/DGS10) to cover the full ~10y
    window — the default 400 covers only ~1.6y. Harmless for the lower-
    frequency series, which simply return however many observations exist."""
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
    """Reconstruct a lagged compute_macro()-shaped dict as of a historical date.
    Latest revised values remain a known historical-vintage limitation. Reuses
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
    """→ (dates, label_end_dates, X, y) pooled across the universe. Technical
    features use history ≤ i only, plus lagged, latest-revised macro features
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

    dates, label_ends, rows, labels = [], [], [], []
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
            stock_end = bars["dates"][i + HORIZON_DAYS].date()
            benchmark = _spx_fwd_return(spx_dates, spx_closes, sample_date, stock_end)
            if benchmark is None:
                continue
            fwd_spx, benchmark_end = benchmark
            rel = fwd_stock - fwd_spx
            if abs(rel) < DEAD_ZONE:  # not a callable outperform/underperform
                continue
            macro_snapshot = _macro_snapshot_asof(macro_lagged, sample_date)
            combined = {**technical, **macro_feat.from_macro_snapshot(macro_snapshot)}
            row = [combined.get(name, np.nan) for name in COMBINED_FEATURE_NAMES]
            dates.append(bars["dates"][i])
            label_ends.append(max(stock_end, benchmark_end))
            rows.append(row)
            labels.append(1 if rel > 0 else 0)
            made += 1
        print(f"  {ticker}: {made} samples")
    return (np.array(dates, dtype="datetime64[D]"),
            np.array(label_ends, dtype="datetime64[D]"),
            np.array(rows, dtype=float), np.array(labels, dtype=int))


def _new_model():
    """One shared model config: shallow trees, slow learning rate, L2 reg and
    early stopping — robust defaults for a wide, noisy financial panel."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(
        max_depth=4, learning_rate=0.03, max_iter=600, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.15, random_state=0)


def purged_date_splits(dates, label_end_dates, n_splits: int = 5):
    """Whole-date expanding folds; every training outcome ends before test starts."""
    from sklearn.model_selection import TimeSeriesSplit

    dates = np.asarray(dates, dtype="datetime64[D]")
    ends = np.asarray(label_end_dates, dtype="datetime64[D]")
    if len(dates) != len(ends) or np.isnat(dates).any() or np.isnat(ends).any() \
            or (ends < dates).any():
        raise ValueError("sample dates and outcome end dates must be valid and aligned")
    unique_dates = np.unique(dates)
    for train_dates, test_dates in TimeSeriesSplit(n_splits=n_splits).split(unique_dates):
        first_test = unique_dates[test_dates[0]]
        train = np.flatnonzero(np.isin(dates, unique_dates[train_dates]) & (ends < first_test))
        test = np.flatnonzero(np.isin(dates, unique_dates[test_dates]))
        if not len(train):
            raise ValueError("not enough dated history after outcome purging")
        yield train, test


def importance_split(dates, label_end_dates):
    """Last 20% of complete dates held out, with the same outcome-end purge."""
    dates = np.asarray(dates, dtype="datetime64[D]")
    ends = np.asarray(label_end_dates, dtype="datetime64[D]")
    unique_dates = np.unique(dates)
    if len(unique_dates) < 2 or len(dates) != len(ends) \
            or np.isnat(dates).any() or np.isnat(ends).any() or (ends < dates).any():
        raise ValueError("importance holdout requires valid sample and outcome dates")
    first_test = unique_dates[min(int(len(unique_dates) * 0.8), len(unique_dates) - 1)]
    train = np.flatnonzero((dates < first_test) & (ends < first_test))
    test = np.flatnonzero(dates >= first_test)
    if not len(train):
        raise ValueError("not enough dated history for a purged importance holdout")
    return train, test


def _validate(X, y, dates, label_end_dates, names):
    """Time-ordered out-of-sample validation. Returns mean accuracy + AUC over
    the splits — the honest skill estimate the lens is required to report."""
    from sklearn.metrics import accuracy_score, roc_auc_score

    accs, aucs = [], []
    for train_idx, test_idx in purged_date_splits(dates, label_end_dates):
        X_train, kept_names = _drop_degenerate_columns(X[train_idx], names)
        keep = [names.index(name) for name in kept_names]
        if len(set(y[train_idx])) < 2 or not kept_names:
            raise ValueError("training fold lacks two classes or usable features")
        m = _new_model()
        m.fit(X_train, y[train_idx])
        proba = m.predict_proba(X[test_idx][:, keep])[:, list(m.classes_).index(1)]
        accs.append(accuracy_score(y[test_idx], (proba >= 0.5).astype(int)))
        if len(set(y[test_idx])) > 1:
            aucs.append(roc_auc_score(y[test_idx], proba))
    return {"accuracy": round(float(np.mean(accs)), 4),
            "auc": round(float(np.mean(aucs)), 4) if aucs else None,
            "n_splits": 5, "positive_rate": round(float(np.mean(y)), 4),
            "protocol": VALIDATION_PROTOCOL,
            "feature_selection": "training_slice_only"}


def _drop_degenerate_columns(X, names: list[str]):
    """Select usable columns from ONLY the supplied training slice."""
    keep_idx, kept_names = [], []
    for j, name in enumerate(names):
        col = X[:, j]
        if len(np.unique(col[np.isfinite(col)])) >= 2:
            keep_idx.append(j)
            kept_names.append(name)
    return X[:, keep_idx], kept_names


def main():
    import joblib
    from sklearn.inspection import permutation_importance

    print(f"Downloading {len(UNIVERSE)} tickers x ~{YEARS}y daily...")
    dates, label_ends, X, y = _build_samples()
    if len(y) < 500:
        raise SystemExit(f"only {len(y)} samples — too few to train credibly")

    order = np.argsort(dates)  # chronological pooled panel
    dates, label_ends, X, y = dates[order], label_ends[order], X[order], y[order]
    print(f"Total {len(y)} samples, {y.mean():.1%} positive.")
    print("Validating...")
    metrics = _validate(X, y, dates, label_ends, COMBINED_FEATURE_NAMES)
    print(f"  OOS accuracy={metrics['accuracy']} auc={metrics['auc']}")

    # Fit the shipped model on ALL data; importances via permutation on a
    # held-out tail so they reflect out-of-sample behaviour, not train fit.
    model = _new_model()
    train, test = importance_split(dates, label_ends)
    X_train, importance_names = _drop_degenerate_columns(X[train], COMBINED_FEATURE_NAMES)
    keep = [COMBINED_FEATURE_NAMES.index(name) for name in importance_names]
    model.fit(X_train, y[train])
    perm = permutation_importance(model, X[test][:, keep], y[test], n_repeats=10,
                                  random_state=0)
    importances = {name: round(float(imp), 5)
                   for name, imp in zip(importance_names, perm.importances_mean)}
    X, feature_names = _drop_degenerate_columns(X, COMBINED_FEATURE_NAMES)
    model = _new_model()
    model.fit(X, y)  # final refit on everything for the artifact

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model,
        "feature_names": feature_names,
        "trained_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "validation_metrics": metrics,
        "validation_protocol": VALIDATION_PROTOCOL,
        "research_limitations": RESEARCH_LIMITATIONS,
        "feature_importances": importances,
        "horizon_days": HORIZON_DAYS,
        "universe": UNIVERSE,
        "label": f"beats {BENCHMARK} by >{DEAD_ZONE:.0%} over {HORIZON_DAYS}d",
    }, ARTIFACT)
    print(f"Saved {ARTIFACT}")
    print("Restart the app — the ML Alpha lens will now show enabled.")


if __name__ == "__main__":
    main()
