"""ML Alpha inference — loads the offline-trained model artifact and scores one
ticker's price history into a directional prediction. This is what promotes the
"Machine Learning Alpha Extractor" from a disabled lens to a live one: the
analyst narrates these experimental model outputs, it never role-plays a
model (see llm/prompts/ml_alpha.md).

Pure local compute — reads a committed .joblib file and runs a forward pass. No
network, so it is safe under the offline test tripwire. The feed reports down
until the artifact exists (the user produces it with scripts/train_ml_alpha.py);
until then the lens correctly shows disabled, exactly like it does today.

Artifact bundle shape (written by the trainer):
    {"model", "feature_names", "trained_at", "validation_metrics",
     "feature_importances", "horizon_days", "universe"}
"""
from functools import lru_cache
from pathlib import Path

from ..skills import ml_features as feat
from ..skills import ml_macro_features as macro_feat

ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "models" / "ml_alpha_v1.joblib"
_KNOWN_FEATURE_NAMES = set(feat.FEATURE_NAMES) | set(macro_feat.MACRO_FEATURE_NAMES)
VALIDATION_PROTOCOL = "purged_date_groups_v1"
RESEARCH_LIMITATIONS = [
    "Current curated universe; survivorship bias is not controlled.",
    "Latest revised FRED history with a uniform 45-day lag; historical vintages are unavailable.",
    "Local-currency equity returns versus a USD benchmark; historical FX is not included.",
]


@lru_cache(maxsize=1)
def _load_bundle():
    """Load once and cache. Returns the bundle dict, or None if sklearn/joblib
    aren't installed or no artifact has been trained yet. Any load failure
    degrades to 'feed down' rather than crashing a report run."""
    try:
        import joblib  # noqa: F401  (also confirms sklearn's runtime is present)
        import sklearn  # noqa: F401
    except ImportError:
        return None
    if not ARTIFACT_PATH.exists():
        return None
    try:
        bundle = joblib.load(ARTIFACT_PATH)
    except Exception:  # corrupt/incompatible artifact — treat as no model
        return None
    names = bundle.get("feature_names") or []
    if not names or not set(names) <= _KNOWN_FEATURE_NAMES:
        # Artifact references a feature this code doesn't know how to compute
        # (technical-only and technical+macro artifacts are both valid shapes;
        # only an UNKNOWN name — a stale/foreign artifact — gets refused).
        return None
    bundle = dict(bundle)
    metrics = bundle.get("validation_metrics") or {}
    purged = (bundle.get("validation_protocol") == VALIDATION_PROTOCOL
              and metrics.get("protocol") == VALIDATION_PROTOCOL)
    bundle["validation_status"] = "purged_date_validation" if purged else "experimental"
    bundle["validation_note"] = (
        "Purged whole-date validation; research limitations still apply."
        if purged else "Legacy artifact lacks purged date-group validation; "
                       "accuracy, AUC and holdout importances withheld. Predictions are experimental.")
    if not purged:
        bundle["validation_metrics"] = {}
        bundle["feature_importances"] = {}
    bundle.setdefault("research_limitations", RESEARCH_LIMITATIONS)
    return bundle


def model_available() -> bool:
    """True when a usable, feature-compatible artifact is loadable — drives the
    `ml_model` entry in ProviderRegistry.feed_status()."""
    return _load_bundle() is not None


def predict(daily: dict | None, macro: dict | None = None) -> dict | None:
    """Score one ticker's daily OHLCV ({"closes","highs","lows","volumes"}),
    optionally with a live `macro.compute_macro()`-shaped snapshot for macro
    context. Returns {prediction, probability, label, feature_importances,
    validation_metrics, trained_at, horizon_days, bars_used} or None when
    there's no model or too little history. The model predicts whether the
    stock BEATS its benchmark (e.g. S&P 500) over `horizon_days` — not raw
    up/down — see `label` for the exact trained definition. `probability` is
    P(outperform); `prediction` is the argmax label. feature_importances /
    validation_metrics are the model's stored global values (a model
    property, not per-prediction). Missing `macro` degrades those columns to
    NaN — never crashes the technical-only path."""
    bundle = _load_bundle()
    if not bundle or not daily:
        return None
    closes = daily.get("closes") or []
    if len(closes) < feat.MIN_BARS:
        return None
    technical = feat.feature_at(closes, daily.get("highs", []), daily.get("lows", []),
                                daily.get("volumes", []), len(closes) - 1)
    if technical is None:
        return None
    combined = {**technical, **macro_feat.from_macro_snapshot(macro)}
    row = [combined.get(name) for name in bundle["feature_names"]]

    import numpy as np
    model = bundle["model"]
    X = np.asarray([row], dtype=float)
    # classes_ are [0, 1] = [underperform, outperform]; P(class 1).
    proba_outperform = float(model.predict_proba(X)[0][list(model.classes_).index(1)])
    return {
        "prediction": "outperform" if proba_outperform >= 0.5 else "underperform",
        "probability": round(proba_outperform, 4),
        "label": bundle.get("label"),
        "feature_importances": bundle.get("feature_importances", {}),
        "validation_metrics": bundle.get("validation_metrics", {}),
        "validation_status": bundle["validation_status"],
        "validation_note": bundle["validation_note"],
        "research_limitations": bundle["research_limitations"],
        "trained_at": bundle.get("trained_at"),
        "horizon_days": bundle.get("horizon_days"),
        "bars_used": len(closes),
    }
