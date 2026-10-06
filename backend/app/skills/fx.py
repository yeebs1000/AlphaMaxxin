"""Multi-currency conversion — generalizes runner.py's get_usd_per_sgd.
Rates come pre-fetched from the Yahoo provider ({"SGD": 0.78, ...} = USD per
1 unit). Missing rates withhold valuation instead of guessing."""
from ..data.base import to_number

def usd_rate(ccy: str, rates: dict | None = None) -> float | None:
    """USD per currency unit; USD is exact, other rates must be supplied."""
    ccy = (ccy or "USD").upper()
    if ccy == "USD":
        return 1.0
    rate = to_number((rates or {}).get(ccy))
    return rate if rate is not None and rate > 0 else None


def to_usd(amount: float, ccy: str, rates: dict | None = None) -> float:
    rate = usd_rate(ccy, rates)
    if rate is None:
        raise ValueError(f"no USD exchange rate for {ccy}")
    return amount * rate
