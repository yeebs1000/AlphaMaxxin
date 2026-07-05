"""Portfolio summary — port of runner.get_metrics_sync with fetching
decoupled: quotes and FX rates come in pre-fetched, valuation is pure math.

holdings: [{ticker, company, quantity, cost_price, currency}]
quotes: {ticker: {"price": ..., "currency": ..., "change_pct": ...}}
fx_rates: {"SGD": 0.78, ...} USD per unit
"""
from .fx import to_usd


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
        if not quote or quote.get("price") is None:
            errors.append(f"no price for {ticker}")
            continue
        ccy = quote.get("currency") or h.get("currency", "USD")
        qty = h.get("quantity", 0)
        value_usd = to_usd(qty * quote["price"], ccy, fx_rates)
        cost_usd = to_usd(qty * (h.get("cost_price") or 0), ccy, fx_rates)
        total_usd += value_usd
        total_cost_usd += cost_usd
        rows.append({
            "ticker": ticker,
            "company": h.get("company", ticker),
            "quantity": qty,
            "price": quote["price"],
            "currency": ccy,
            "value_usd": value_usd,
            "cost_usd": cost_usd,
            "pl_usd": value_usd - cost_usd,
            "day_change_pct": quote.get("change_pct"),
        })
    for row in rows:
        row["weight"] = row["value_usd"] / total_usd if total_usd else 0.0

    day_change_usd = sum(
        r["value_usd"] * (r["day_change_pct"] / 100)
        for r in rows if r.get("day_change_pct") is not None
    )
    return {
        "total_value_usd": total_usd,
        "total_cost_usd": total_cost_usd,
        "total_pl_usd": total_usd - total_cost_usd,
        "day_change_usd": day_change_usd,
        "holdings_count": len(rows),
        "holdings": rows,
        "by_currency": _by_currency(rows),
        "benchmark": benchmark_quote,
        "errors": errors,
    }


def _by_currency(rows: list[dict]) -> dict:
    out: dict[str, float] = {}
    for r in rows:
        out[r["currency"]] = out.get(r["currency"], 0.0) + r["value_usd"]
    return out
