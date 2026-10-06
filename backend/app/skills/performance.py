"""Portfolio summary — port of runner.get_metrics_sync with fetching
decoupled: quotes and FX rates come in pre-fetched, valuation is pure math.

holdings: [{ticker, company, quantity, cost_price, currency}]
quotes: {ticker: {"price": ..., "currency": ..., "change_pct": ...}}
fx_rates: {"SGD": 0.78, ...} USD per unit
"""
from .fx import to_usd, usd_rate
from ..data.base import to_number


def portfolio_summary(holdings: list[dict], quotes: dict,
                      fx_rates: dict | None = None,
                      benchmark_quote: dict | None = None) -> dict:
    rows = []
    total_usd = 0.0
    total_cost_usd = 0.0
    errors = []
    for h in holdings:
        ticker = h["ticker"]
        quote = quotes.get(ticker)
        price = to_number((quote or {}).get("price"))
        if price is None or price <= 0:
            errors.append(f"no price for {ticker}")
            continue
        ccy = quote.get("currency") or h.get("currency", "USD")
        cost_ccy = h.get("currency") or ccy
        if usd_rate(ccy, fx_rates) is None or usd_rate(cost_ccy, fx_rates) is None:
            errors.append(f"no USD exchange rate for {ticker} ({ccy}/{cost_ccy})")
            continue
        qty = h.get("quantity", 0)
        value_usd = to_usd(qty * price, ccy, fx_rates)
        cost_usd = to_usd(qty * (h.get("cost_price") or 0), cost_ccy, fx_rates)
        total_usd += value_usd
        total_cost_usd += cost_usd
        change = to_number(quote.get("change_pct"))
        day_change = value_usd * change / (100 + change) if change is not None and change > -100 else None
        rows.append({
            "ticker": ticker,
            "company": h.get("company", ticker),
            "quantity": qty,
            "price": quote["price"],
            "currency": ccy,
            "value_usd": value_usd,
            "cost_usd": cost_usd,
            "pl_usd": value_usd - cost_usd,
            "day_change_pct": change,
            "day_change_usd": day_change,
        })
    for row in rows:
        row["weight"] = None if errors else row["value_usd"] / total_usd if total_usd else 0.0

    day_complete = not errors and all(r["day_change_usd"] is not None for r in rows if r["quantity"])
    day_change_usd = sum(r["day_change_usd"] or 0 for r in rows) if day_complete else None
    return {
        "total_value_usd": total_usd,
        "total_cost_usd": total_cost_usd,
        "total_pl_usd": total_usd - total_cost_usd,
        "day_change_usd": day_change_usd,
        "day_change_complete": day_complete,
        "holdings_count": len(rows),
        "holdings": rows,
        "by_currency": _by_currency(rows),
        "benchmark": benchmark_quote,
        "errors": errors,
        "valuation_complete": not errors,
    }


def _by_currency(rows: list[dict]) -> dict:
    out: dict[str, float] = {}
    for r in rows:
        out[r["currency"]] = out.get(r["currency"], 0.0) + r["value_usd"]
    return out
