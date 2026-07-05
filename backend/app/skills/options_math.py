"""Black-Scholes pricing and Greeks. Pure math — used by the
Technicals+Options analyst when option-chain data is available (US tickers
via yfinance); everything degrades to stock-only elsewhere."""
import math


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> float:
    """European option price. kind: "call" | "put". T in years."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        intrinsic = max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)
        return intrinsic
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if kind == "call":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def greeks(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> dict:
    """{delta, gamma, vega, theta, rho}. Vega per 1.0 vol point; theta per year."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    gamma = _norm_pdf(d1) / (S * sigma * sqrt_t)
    vega = S * _norm_pdf(d1) * sqrt_t
    if kind == "call":
        delta = _norm_cdf(d1)
        theta = (-S * _norm_pdf(d1) * sigma / (2 * sqrt_t)
                 - r * K * math.exp(-r * T) * _norm_cdf(d2))
        rho = K * T * math.exp(-r * T) * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (-S * _norm_pdf(d1) * sigma / (2 * sqrt_t)
                 + r * K * math.exp(-r * T) * _norm_cdf(-d2))
        rho = -K * T * math.exp(-r * T) * _norm_cdf(-d2)
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


def put_call_parity_gap(call: float, put: float, S: float, K: float,
                        T: float, r: float) -> float:
    """C - P - (S - K*e^-rT); zero for consistent European prices."""
    return call - put - (S - K * math.exp(-r * T))


def chain_summary(chain: dict, r: float = 0.045) -> dict | None:
    """Compact per-ticker options view for the analyst from a provider chain
    ({"expiry","spot","calls","puts"}): ATM IV, straddle-implied move, and
    highest-OI strikes."""
    if not chain or not chain.get("spot"):
        return None
    spot = chain["spot"]
    calls, puts = chain.get("calls", []), chain.get("puts", [])
    if not calls or not puts:
        return None

    def nearest(rows):
        return min(rows, key=lambda x: abs(x["strike"] - spot))

    atm_call, atm_put = nearest(calls), nearest(puts)
    atm_iv = (atm_call["iv"] + atm_put["iv"]) / 2 if atm_call["iv"] and atm_put["iv"] else \
        atm_call["iv"] or atm_put["iv"] or None
    straddle = (atm_call["last"] or (atm_call["bid"] + atm_call["ask"]) / 2) + \
               (atm_put["last"] or (atm_put["bid"] + atm_put["ask"]) / 2)
    implied_move_pct = (straddle / spot) * 100 if spot else None
    top_oi_call = max(calls, key=lambda x: x["oi"], default=None)
    top_oi_put = max(puts, key=lambda x: x["oi"], default=None)
    return {
        "expiry": chain.get("expiry"),
        "spot": spot,
        "atm_iv": atm_iv,
        "straddle_implied_move_pct": implied_move_pct,
        "max_oi_call_strike": top_oi_call["strike"] if top_oi_call else None,
        "max_oi_put_strike": top_oi_put["strike"] if top_oi_put else None,
    }
