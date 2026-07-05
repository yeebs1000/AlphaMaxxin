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
                 sectors: dict | None = None) -> dict:
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
    return report


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

    # Highly correlated pairs (>0.8) — hidden concentration
    tickers = [t for t in weights if t in returns and len(returns[t]) > 1]
    n_bars = min((len(returns[t]) for t in tickers), default=0)
    high_corr = []
    if n_bars >= 20:
        mat = np.array([np.asarray(returns[t], dtype=float)[-n_bars:] for t in tickers])
        corr = np.corrcoef(mat)
        for i in range(len(tickers)):
            for j in range(i + 1, len(tickers)):
                if corr[i, j] > 0.8:
                    high_corr.append({"a": tickers[i], "b": tickers[j],
                                      "corr": float(corr[i, j])})
    out["high_correlation_pairs"] = high_corr
    return out
