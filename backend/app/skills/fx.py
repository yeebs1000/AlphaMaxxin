"""Multi-currency conversion — generalizes runner.py's get_usd_per_sgd.
Rates come pre-fetched from the Yahoo provider ({"SGD": 0.78, ...} = USD per
1 unit); a static fallback keeps valuation alive if a fetch failed."""

FALLBACK_USD_PER = {
    "USD": 1.0,
    "SGD": 0.779,
    "HKD": 0.128,
    "JPY": 0.0065,
    "KRW": 0.00072,
    "CNY": 0.139,
    "EUR": 1.08,
    "GBP": 1.27,
}


def usd_rate(ccy: str, rates: dict | None = None) -> float:
    """USD per 1 unit of ccy; live rate if provided, else static fallback."""
    ccy = (ccy or "USD").upper()
    if rates:
        rate = rates.get(ccy)
        if rate:
            return rate
    return FALLBACK_USD_PER.get(ccy, 1.0)


def to_usd(amount: float, ccy: str, rates: dict | None = None) -> float:
    return amount * usd_rate(ccy, rates)
