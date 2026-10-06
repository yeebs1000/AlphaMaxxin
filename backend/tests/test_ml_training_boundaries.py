"""Training split/metadata contracts without downloading or fitting models."""
import numpy as np

from app.data import ml_model
from scripts import train_ml_alpha as trainer


def _panel():
    dates = np.repeat(np.arange("2020-01-01", "2020-01-31", dtype="datetime64[D]"), 3)
    return dates, dates + np.timedelta64(3, "D")


def test_validation_groups_whole_dates_and_purges_actual_outcome_end_dates():
    dates, ends = _panel()
    for train, test in trainer.purged_date_splits(dates, ends, n_splits=3):
        assert set(dates[train]).isdisjoint(dates[test])
        assert ends[train].max() < dates[test].min()
        assert len(test) % 3 == 0
        assert len(train) % 3 == 0


def test_importance_holdout_obeys_the_same_date_purge():
    dates, ends = _panel()
    train, test = trainer.importance_split(dates, ends)
    assert dates[test].min() == np.datetime64("2020-01-25")
    assert ends[train].max() < dates[test].min()
    assert len(test) == 18


def test_feature_selection_never_inspects_holdout_rows():
    X = np.array([[1., np.nan], [2., np.nan], [3., np.nan], [4., 100.]])
    selected, names = trainer._drop_degenerate_columns(X[:3], ["history", "future"])
    assert names == ["history"]
    assert selected.shape == (3, 1)


def test_legacy_artifact_cannot_supply_validated_accuracy(monkeypatch, tmp_path):
    import joblib
    artifact = tmp_path / "legacy.joblib"
    artifact.touch()
    monkeypatch.setattr(ml_model, "ARTIFACT_PATH", artifact)
    monkeypatch.setattr(joblib, "load", lambda _: {
        "model": object(), "feature_names": ["rsi14"],
        "validation_metrics": {"accuracy": 0.99, "auc": 0.99},
        "feature_importances": {"rsi14": 0.9},
    })
    ml_model._load_bundle.cache_clear()
    try:
        bundle = ml_model._load_bundle()
        assert bundle["validation_metrics"] == {}
        assert bundle["feature_importances"] == {}
        assert bundle["validation_status"] == "experimental"
        assert bundle["validation_note"]
    finally:
        ml_model._load_bundle.cache_clear()
