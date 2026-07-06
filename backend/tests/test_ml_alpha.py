"""ML Alpha lens: feature look-ahead safety, graceful disable without an
artifact, and (when sklearn is installed) real inference + skill wiring.

All offline. The real model is produced by scripts/train_ml_alpha.py (network,
user-run); here we fabricate a tiny model in-memory so nothing touches the wire.
"""
import numpy as np
import pytest

from app.skills import ml_features as feat
from app.skills import ml_alpha
from app.data import ml_model
from app.llm import analysts as an


def _bars(n=260, seed=0):
    rng = np.random.default_rng(seed)
    closes = list(np.cumsum(rng.normal(0, 1, n)) + 300)
    return {"closes": closes, "highs": [c + 1 for c in closes],
            "lows": [c - 1 for c in closes],
            "volumes": list(rng.integers(1000, 5000, n).astype(float))}


# ---- pure-numpy: always run, no sklearn needed --------------------------------

def test_feature_row_deterministic_and_no_lookahead():
    b = _bars()
    r1 = feat.feature_row(b["closes"], b["highs"], b["lows"], b["volumes"], 250)
    r2 = feat.feature_row(b["closes"], b["highs"], b["lows"], b["volumes"], 250)
    assert r1 == r2 and len(r1) == len(feat.FEATURE_NAMES)
    # Mutating a future bar must not change the feature at 250.
    tampered = list(b["closes"]); tampered[255] += 500
    r3 = feat.feature_row(tampered, b["highs"], b["lows"], b["volumes"], 250)
    assert r1 == r3


def test_feature_at_thin_history_is_none():
    b = _bars()
    assert feat.feature_at(b["closes"], b["highs"], b["lows"], b["volumes"], 50) is None


def test_lens_disabled_without_model():
    status = {"ml_model": False}
    ml = next(l for l in an.lens_status(status) if l["id"] == "ml_alpha")
    assert ml["enabled"] is False and ml["kind"] == "analyst"


def test_lens_enabled_when_feed_up():
    status = {"ml_model": True}
    ml = next(l for l in an.lens_status(status) if l["id"] == "ml_alpha")
    assert ml["enabled"] is True


def test_predict_and_skill_noop_without_artifact(monkeypatch, tmp_path):
    # No artifact present → feed down, predict None, skill returns {}.
    monkeypatch.setattr(ml_model, "ARTIFACT_PATH", tmp_path / "nope.joblib")
    ml_model._load_bundle.cache_clear()
    assert ml_model.model_available() is False
    assert ml_model.predict(_bars()) is None
    assert ml_alpha.predict_targets(["MSFT"], {"MSFT": _bars()}) == {}


# ---- inference with a real (synthetic) model: needs sklearn -------------------

def _fake_artifact(path):
    joblib = pytest.importorskip("joblib")
    from sklearn.ensemble import HistGradientBoostingClassifier
    rng = np.random.default_rng(1)
    X = rng.normal(size=(400, len(feat.FEATURE_NAMES)))
    y = (X[:, 0] + rng.normal(scale=0.3, size=400) > 0).astype(int)  # learnable signal
    model = HistGradientBoostingClassifier(max_iter=50, random_state=0).fit(X, y)
    joblib.dump({
        "model": model, "feature_names": feat.FEATURE_NAMES,
        "trained_at": "2026-01-01T00:00:00+00:00",
        "validation_metrics": {"accuracy": 0.55, "auc": 0.58},
        "feature_importances": {n: 0.1 for n in feat.FEATURE_NAMES},
        "horizon_days": 20, "universe": ["AAPL"],
    }, path)


def test_predict_shape_with_model(monkeypatch, tmp_path):
    pytest.importorskip("sklearn")
    artifact = tmp_path / "ml_alpha_v1.joblib"
    _fake_artifact(artifact)
    monkeypatch.setattr(ml_model, "ARTIFACT_PATH", artifact)
    ml_model._load_bundle.cache_clear()

    assert ml_model.model_available() is True
    pred = ml_model.predict(_bars())
    assert pred["prediction"] in ("up", "down")
    assert 0.0 <= pred["probability"] <= 1.0
    assert pred["validation_metrics"]["accuracy"] == 0.55
    assert pred["trained_at"] == "2026-01-01T00:00:00+00:00"
    assert set(pred["feature_importances"]) == set(feat.FEATURE_NAMES)

    out = ml_alpha.predict_targets(["MSFT", "AAPL"], {"MSFT": _bars(), "AAPL": _bars(n=50)})
    assert "MSFT" in out and "AAPL" not in out  # thin-history ticker just absent
    ml_model._load_bundle.cache_clear()  # don't leak the fake into other tests


def test_feature_mismatch_artifact_refused(monkeypatch, tmp_path):
    joblib = pytest.importorskip("joblib")
    pytest.importorskip("sklearn")
    from sklearn.ensemble import HistGradientBoostingClassifier
    artifact = tmp_path / "bad.joblib"
    X = np.random.default_rng(2).normal(size=(50, 3))
    model = HistGradientBoostingClassifier(max_iter=10).fit(X, [0, 1] * 25)
    joblib.dump({"model": model, "feature_names": ["a", "b", "c"]}, artifact)
    monkeypatch.setattr(ml_model, "ARTIFACT_PATH", artifact)
    ml_model._load_bundle.cache_clear()
    assert ml_model.model_available() is False  # column mismatch → refused
    ml_model._load_bundle.cache_clear()
