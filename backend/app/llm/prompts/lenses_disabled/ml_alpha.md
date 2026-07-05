# Machine Learning Alpha Extractor — DISABLED LENS

Status: disabled until a real, offline-trained model artifact plus an
inference provider are added and registered in
`ProviderRegistry.feed_status()` as `ml_model`. In v1 this agent asked the
LLM to role-play gradient boosting and LSTMs; v2 keeps the lens registered
but off — an LLM narrating imaginary model output is not machine learning.

To enable (contribution welcome): train a model offline (e.g. gradient
boosting over the skills layer's indicator features), commit the artifact +
training notebook, add an inference provider that outputs per-ticker
{prediction, feature_importances, trained_at, validation_metrics}, flip
`ml_model` on, and flesh out this prompt following the active-analyst
pattern. Validation metrics are mandatory — no unvalidated signal ships.

## Duties once enabled
Interpret supplied model predictions and feature importances for the run's
targets; always report the model's validation metrics and age alongside any
signal; flag regime mismatch between training window and current macro.
