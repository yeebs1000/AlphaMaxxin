"""Technicals: hand-computed sanity values (parity with the removed v1
technical_indicators.py was verified during the v2 migration and no longer
needs a standing test now that v1 is gone). Options math: known
Black-Scholes value and put-call parity."""
import math
import random

import pytest

from app.skills import technicals as v2
from app.skills import options_math


def synthetic_ohlcv(n=260, seed=42):
    """Deterministic random-walk bars, same shape as the providers return."""
    rng = random.Random(seed)
    closes, highs, lows, volumes = [], [], [], []
    price = 100.0
    for _ in range(n):
        price = max(1.0, price * (1 + rng.uniform(-0.03, 0.032)))
        spread = price * rng.uniform(0.005, 0.02)
        closes.append(price)
        highs.append(price + spread)
        lows.append(price - spread)
        volumes.append(rng.randint(100_000, 5_000_000))
    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}


BARS = synthetic_ohlcv()


def test_hand_computed_values():
    assert v2.sma([1, 2, 3, 4, 5], 5) == 3.0
    assert v2.sma([1, 2, 3, 4, 5], 3) == 4.0  # last 3
    assert v2.sma([1, 2], 5) is None
    # Monotonic rise → RSI 100 (no losses)
    assert v2.rsi(list(range(1, 40))) == 100.0
    # Symmetric alternation ±1 around 100 → RSI 50
    alternating = [100 + (1 if i % 2 else 0) for i in range(40)]
    assert v2.rsi(alternating) == pytest.approx(50.0, abs=5)


def test_snapshot_structure_and_signal():
    snap = v2.compute_snapshot("TEST", BARS, higher=None)
    assert snap["ticker"] == "TEST"
    assert snap["bars_used"] == 260
    assert snap["last_close"] == BARS["closes"][-1]
    sig = snap["signal"]
    assert -100 <= sig["score"] <= 100
    assert sig["label"] in ("strong buy", "buy", "hold", "sell", "strong sell")
    assert isinstance(sig["reasons"], list) and sig["reasons"]


def test_snapshot_higher_timeframe_trend():
    rising = {"closes": [float(i) for i in range(1, 120)],
              "highs": [float(i) + 1 for i in range(1, 120)],
              "lows": [float(i) - 1 for i in range(1, 120)],
              "volumes": [1000.0] * 119}
    snap = v2.compute_snapshot("UP", rising, higher=rising)
    assert snap["higher_timeframe_trend"] == "Uptrend"


def test_snapshot_none_on_empty():
    assert v2.compute_snapshot("X", {"closes": [], "highs": [], "lows": [], "volumes": []}) is None
    assert v2.compute_snapshot("X", None) is None


# ---------------------------------------------------------------------------
# Options math
# ---------------------------------------------------------------------------
def test_bs_known_value():
    # Classic textbook case: S=100, K=100, T=1y, r=5%, sigma=20% → call 10.4506
    call = options_math.bs_price(100, 100, 1.0, 0.05, 0.20, "call")
    assert call == pytest.approx(10.4506, abs=1e-3)
    put = options_math.bs_price(100, 100, 1.0, 0.05, 0.20, "put")
    assert put == pytest.approx(5.5735, abs=1e-3)


def test_put_call_parity():
    S, K, T, r, sigma = 105.0, 95.0, 0.5, 0.045, 0.35
    call = options_math.bs_price(S, K, T, r, sigma, "call")
    put = options_math.bs_price(S, K, T, r, sigma, "put")
    assert options_math.put_call_parity_gap(call, put, S, K, T, r) == pytest.approx(0.0, abs=1e-9)


def test_greeks_signs_and_delta_parity():
    g_call = options_math.greeks(100, 100, 1.0, 0.05, 0.2, "call")
    g_put = options_math.greeks(100, 100, 1.0, 0.05, 0.2, "put")
    assert 0 < g_call["delta"] < 1
    assert -1 < g_put["delta"] < 0
    assert g_call["delta"] - g_put["delta"] == pytest.approx(1.0, abs=1e-9)  # N(d1)-(N(d1)-1)
    assert g_call["gamma"] == pytest.approx(g_put["gamma"])
    assert g_call["vega"] == pytest.approx(g_put["vega"])
    assert g_call["gamma"] > 0 and g_call["vega"] > 0


def test_expired_option_is_intrinsic():
    assert options_math.bs_price(110, 100, 0.0, 0.05, 0.2, "call") == 10.0
    assert options_math.bs_price(90, 100, 0.0, 0.05, 0.2, "put") == 10.0


def test_chain_summary():
    chain = {
        "expiry": "2026-07-18", "spot": 100.0,
        "calls": [{"strike": 95, "last": 6.0, "bid": 0, "ask": 0, "iv": 0.3, "oi": 50},
                  {"strike": 100, "last": 3.0, "bid": 0, "ask": 0, "iv": 0.32, "oi": 500}],
        "puts": [{"strike": 100, "last": 2.8, "bid": 0, "ask": 0, "iv": 0.30, "oi": 800},
                 {"strike": 105, "last": 6.5, "bid": 0, "ask": 0, "iv": 0.35, "oi": 20}],
    }
    s = options_math.chain_summary(chain)
    assert s["atm_iv"] == pytest.approx(0.31)
    assert s["straddle_implied_move_pct"] == pytest.approx(5.8)  # (3.0+2.8)/100
    assert s["max_oi_call_strike"] == 100
    assert s["max_oi_put_strike"] == 100
    assert options_math.chain_summary(None) is None
