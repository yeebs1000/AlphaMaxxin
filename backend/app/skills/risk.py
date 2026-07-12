"""Portfolio risk metrics — concentration, exposure, VaR/CVaR, beta,
drawdown, correlations. Standard formulas over pre-fetched returns; the Risk
analyst narrates these numbers, it never computes its own.

holdings: [{ticker, company, quantity, cost_price, currency}]
values_usd: {ticker: current market value in USD}
returns: {ticker: [daily pct returns]} aligned oldest→newest
benchmark_returns: [daily pct returns] for the benchmark (e.g. SPY)
"""
import numpy as np


def compute_risk(holdings: list[dict], values_usd: dict,
                 returns: dict | None = None,
                 benchmark_returns: list | None = None,
                 sectors: dict | None = None,
                 adv_usd: dict | None = None) -> dict:
    """adv_usd: {ticker: average daily traded value in USD} — enables the
    liquidity (days-to-liquidate) block when supplied."""
    total = sum(values_usd.get(h["ticker"], 0.0) for h in holdings)
    weights = {h["ticker"]: (values_usd.get(h["ticker"], 0.0) / total if total else 0.0)
               for h in holdings}

    # Concentration
    hhi = sum(w * w for w in weights.values())
    top = max(weights.items(), key=lambda kv: kv[1], default=(None, 0.0))

    # Currency exposure
    currency_exposure: dict[str, float] = {}
    for h in holdings:
        ccy = h.get("currency", "USD")
        currency_exposure[ccy] = currency_exposure.get(ccy, 0.0) + weights[h["ticker"]]

    # Sector exposure (sectors map is optional — from fundamentals/moomoo)
    sector_weights: dict[str, float] = {}
    for h in holdings:
        sector = (sectors or {}).get(h["ticker"], "Unknown")
        sector_weights[sector] = sector_weights.get(sector, 0.0) + weights[h["ticker"]]

    report = {
        "portfolio_value_usd": total,
        "holdings_count": len(holdings),
        "weights": weights,
        "hhi": hhi,
        "top_position": {"ticker": top[0], "weight": top[1]},
        "currency_exposure": currency_exposure,
        "sector_weights": sector_weights,
        "flags": _concentration_flags(weights, sector_weights, currency_exposure),
    }

    if returns:
        report.update(_return_based_metrics(weights, returns, benchmark_returns))
    report["stress_scenarios"] = _stress_scenarios(
        report.get("portfolio_beta"), currency_exposure, total)
    if adv_usd:
        report["liquidity"] = _liquidity(values_usd, adv_usd)
    return report


# Shock grid: index moves applied through portfolio beta; FX applied to the
# non-USD share of the book. Linear beta approximations — a real desk layers
# convexity/factor models on top; the analyst must present these as estimates.
_SCENARIOS = [
    {"name": "index -5%", "index_pct": -5.0, "usd_up_pct": 0.0},
    {"name": "index -10%", "index_pct": -10.0, "usd_up_pct": 0.0},
    {"name": "index -20% (crash)", "index_pct": -20.0, "usd_up_pct": 0.0},
    {"name": "risk-off (index -10%, USD +3%)", "index_pct": -10.0, "usd_up_pct": 3.0},
    {"name": "USD +5% (FX shock only)", "index_pct": 0.0, "usd_up_pct": 5.0},
]


def _stress_scenarios(beta, currency_exposure: dict, total_usd: float) -> list[dict]:
    """Estimated portfolio P&L under each shock. Needs beta for the index leg
    (falls back to 1.0 with a flag when returns were unavailable)."""
    beta_used = beta if beta is not None else 1.0
    foreign_weight = sum(w for ccy, w in currency_exposure.items() if ccy != "USD")
    out = []
    for s in _SCENARIOS:
        pnl_pct = beta_used * s["index_pct"] - foreign_weight * s["usd_up_pct"]
        out.append({"scenario": s["name"],
                    "est_pnl_pct": round(pnl_pct, 2),
                    "est_pnl_usd": round(total_usd * pnl_pct / 100, 0),
                    "beta_assumed": beta is None})
    return out


def _liquidity(values_usd: dict, adv_usd: dict) -> dict:
    """Days to exit each position at 10% of average daily traded value — the
    standard participation-rate yardstick. Flags positions needing >5 days."""
    per_position = {}
    slow = []
    for ticker, value in values_usd.items():
        adv = adv_usd.get(ticker)
        if not adv or not value:
            continue
        days = value / (adv * 0.10)
        per_position[ticker] = round(days, 1)
        if days > 5:
            slow.append(ticker)
    return {"days_to_liquidate_10pct": per_position,
            "participation_rate": 0.10,
            "slow_to_exit": slow}


def _concentration_flags(weights, sector_weights, currency_exposure) -> list[str]:
    flags = []
    for ticker, w in weights.items():
        if w > 0.20:
            flags.append(f"{ticker} is {w:.0%} of the portfolio (>20% single-name)")
    for sector, w in sector_weights.items():
        if sector != "Unknown" and w > 0.40:
            flags.append(f"{sector} sector is {w:.0%} (>40%)")
    for ccy, w in currency_exposure.items():
        if ccy != "USD" and w > 0.50:
            flags.append(f"{w:.0%} of the book is {ccy}-denominated")
    return flags


def _portfolio_return_series(weights: dict, returns: dict) -> np.ndarray | None:
    series = {t: np.asarray(r, dtype=float) for t, r in returns.items()
              if t in weights and len(r) > 1}
    if not series:
        return None
    n = min(len(r) for r in series.values())
    port = np.zeros(n)
    for t, r in series.items():
        port += weights[t] * r[-n:]
    return port


def _return_based_metrics(weights, returns, benchmark_returns) -> dict:
    out = {}
    port = _portfolio_return_series(weights, returns)
    if port is None or len(port) < 20:
        return out

    # Parametric daily VaR/CVaR at 95% (historical percentile method)
    var_95 = float(np.percentile(port, 5))
    tail = port[port <= var_95]
    cvar_95 = float(np.mean(tail)) if len(tail) else var_95
    out["var_95_1d_pct"] = var_95 * 100
    out["cvar_95_1d_pct"] = cvar_95 * 100
    out["ann_volatility_pct"] = float(np.std(port)) * np.sqrt(252) * 100

    # Max drawdown over the window
    equity = np.cumprod(1 + port)
    peak = np.maximum.accumulate(equity)
    out["max_drawdown_pct"] = float(np.min(equity / peak - 1)) * 100

    # Beta vs benchmark
    if benchmark_returns is not None and len(benchmark_returns) > 1:
        bench = np.asarray(benchmark_returns, dtype=float)
        n = min(len(port), len(bench))
        b, p = bench[-n:], port[-n:]
        var_b = float(np.var(b, ddof=1))  # ddof=1 to match np.cov's sample covariance
        if var_b > 0:
            out["portfolio_beta"] = float(np.cov(p, b)[0, 1] / var_b)

    # Correlation structure — hidden concentration and true diversification
    tickers = [t for t in weights if t in returns and len(returns[t]) > 1]
    n_bars = min((len(returns[t]) for t in tickers), default=0)
    high_corr = []
    if n_bars >= 20 and len(tickers) >= 2:
        mat = np.array([np.asarray(returns[t], dtype=float)[-n_bars:] for t in tickers])
        corr = np.corrcoef(mat)
        pair_corrs = []
        for i in range(len(tickers)):
            for j in range(i + 1, len(tickers)):
                pair_corrs.append(float(corr[i, j]))
                if corr[i, j] > 0.8:
                    high_corr.append({"a": tickers[i], "b": tickers[j],
                                      "corr": float(corr[i, j])})
        out["avg_pairwise_correlation"] = round(float(np.mean(pair_corrs)), 3)
        # Diversification ratio: weighted avg standalone vol / portfolio vol.
        # 1.0 = one bet in different wrappers; higher = real diversification.
        w = np.array([weights[t] for t in tickers])
        vols = mat.std(axis=1, ddof=1)
        port_vol = float(np.std(port, ddof=1))
        if port_vol > 0 and w.sum() > 0:
            out["diversification_ratio"] = round(
                float((w / w.sum() * vols).sum()) / port_vol, 2)
    out["high_correlation_pairs"] = high_corr
    return out
