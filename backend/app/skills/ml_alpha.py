"""ML Alpha skill — per-ticker directional predictions from the offline-trained
model. Thin wrapper over data/ml_model.predict, same shape as order_book.py:
tickers with no model or too little history are simply absent, and the lens
prompt requires flagging those gaps rather than inventing a signal."""
from ..data import ml_model


def predict_targets(tickers: list[str], daily_by_ticker: dict,
                    macro: dict | None = None) -> dict:
    """{ticker: prediction dict} for every ticker the model could score.
    `macro` (a macro.compute_macro()-shaped snapshot) is optional context
    threaded through to every ticker's prediction — missing macro degrades
    those features to NaN, never blocks a technical-only prediction."""
    out = {}
    if not ml_model.model_available():
        return out
    for ticker in tickers:
        pred = ml_model.predict(daily_by_ticker.get(ticker), macro=macro)
        if pred:
            out[ticker] = pred
    return out
