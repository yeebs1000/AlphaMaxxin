"""Macro-derived features for the ML Alpha model — the single source of truth
for turning a `macro.compute_macro()`-shaped dict into a feature row, shared by
both live inference (data/ml_model.py, given TODAY's live snapshot) and the
offline trainer (scripts/train_ml_alpha.py, given a reconstructed historical
snapshot as of each training sample's date). Pure, no network — the network
side (fetching FRED, and for training, respecting real-world publication lag)
lives in the two callers, not here.

Applied identically to every ticker regardless of home market (HK/JP/KR/SG
included) — a deliberate simplification: US rates/dollar/inflation regime is a
real global risk-sentiment driver, but true region-specific macro (BOJ/BOK/PBOC
data) is out of scope for this pass.
"""
import numpy as np

MACRO_FEATURE_NAMES = [
    "cpi_yoy",
    "core_cpi_yoy",
    "ppi_yoy",
    "core_ppi_yoy",
    "curve_2s10s",
    "fed_funds",
    "nfp_change_k",
    "unemployment",
    "fed_dot_gap",
]


def from_macro_snapshot(macro: dict | None) -> dict:
    """macro.compute_macro()-shaped dict -> {feature_name: value|NaN}. A
    missing snapshot or missing field degrades to NaN (HistGBM handles NaN
    natively), never to a guessed number."""
    macro = macro or {}
    inflation = macro.get("inflation") or {}
    producer = macro.get("producer_prices") or {}
    rates = macro.get("rates") or {}
    labor = macro.get("labor") or {}
    dot_plot = macro.get("fed_dot_plot") or {}

    def _or_nan(v):
        return v if v is not None else np.nan

    return {
        "cpi_yoy": _or_nan(inflation.get("cpi_yoy")),
        "core_cpi_yoy": _or_nan(inflation.get("core_cpi_yoy")),
        "ppi_yoy": _or_nan(producer.get("ppi_yoy")),
        "core_ppi_yoy": _or_nan(producer.get("core_ppi_yoy")),
        "curve_2s10s": _or_nan(rates.get("curve_2s10s")),
        "fed_funds": _or_nan(rates.get("fed_funds")),
        "nfp_change_k": _or_nan(labor.get("nonfarm_payrolls_change_k")),
        "unemployment": _or_nan(labor.get("unemployment")),
        "fed_dot_gap": _or_nan(dot_plot.get("market_vs_fed_gap")),
    }


if __name__ == "__main__":
    empty = from_macro_snapshot(None)
    assert set(empty) == set(MACRO_FEATURE_NAMES)
    assert all(v != v for v in empty.values())  # all NaN

    snap = {"inflation": {"cpi_yoy": 3.1, "core_cpi_yoy": 2.8},
            "producer_prices": {"ppi_yoy": 2.0, "core_ppi_yoy": 1.9},
            "rates": {"curve_2s10s": -0.3, "fed_funds": 4.5},
            "labor": {"nonfarm_payrolls_change_k": 150.0, "unemployment": 4.1},
            "fed_dot_plot": {"market_vs_fed_gap": 0.15}}
    row = from_macro_snapshot(snap)
    assert row["cpi_yoy"] == 3.1 and row["fed_dot_gap"] == 0.15
    print("ml_macro_features self-check OK:", row)
