"""Money-weighted return (XIRR) — what YOU actually earned.

TWR and MWR answer different questions and a book needs both:

  • TWR (equity_history.metrics) strips out the timing of deposits, so it
    measures the STRATEGY. It is what a fund reports, because the manager
    does not control when investors add money.
  • MWR/XIRR weights every dollar by how long it was invested, so it measures
    YOUR OUTCOME. Put money in right before a drawdown and MWR falls while
    TWR does not — and MWR is the honest one about your wealth.

The gap between them is itself the signal: MWR well below TWR means money
arrived at bad moments (buying into strength); MWR above TWR means it
arrived at good ones.

XIRR is the rate r solving  sum( cf_i / (1+r)^(days_i/365) ) = 0, where the
final portfolio value is a terminal inflow. Solved by bisection, not
Newton-Raphson: Newton diverges on the flat/irregular flow patterns a real
personal account produces, and a wrong-but-confident number is worse than a
refusal here.
"""
import datetime

_MAX_RATE = 1e6          # +100,000,000%/yr — beyond this we refuse
_MIN_RATE = -0.9999999   # a -100% return is the floor (total loss)
_TOL = 1e-7
_MAX_ITER = 200


def _npv(rate: float, flows: list) -> float:
    """Net present value of [(date, amount)] at an annual `rate`."""
    t0 = flows[0][0]
    total = 0.0
    for when, amount in flows:
        years = (when - t0).days / 365.0
        total += amount / ((1.0 + rate) ** years)
    return total


def xirr(flows: list) -> float | None:
    """Annualised money-weighted return for dated cash flows.

    flows: [(date, amount)] — NEGATIVE for money going INTO the portfolio
    (a purchase/deposit), POSITIVE for money coming OUT (a sale/withdrawal),
    with the current portfolio value as a final positive flow.

    Returns the annual rate as a fraction (0.12 = +12%/yr), or None when the
    problem is unsolvable: fewer than two flows, no sign change (all money in
    or all out — no return is defined), or no root in a sane range.
    """
    flows = sorted((d, float(a)) for d, a in (flows or []) if a)
    if len(flows) < 2:
        return None
    # A return only exists if money both entered and left (or is still there).
    if not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    if flows[0][0] == flows[-1][0]:
        return None                      # zero elapsed time

    lo, hi = _MIN_RATE, _MAX_RATE
    f_lo, f_hi = _npv(lo, flows), _npv(hi, flows)
    if f_lo * f_hi > 0:
        return None                      # no sign change -> no bracketed root
    for _ in range(_MAX_ITER):
        mid = (lo + hi) / 2.0
        f_mid = _npv(mid, flows)
        if abs(f_mid) < _TOL or (hi - lo) < _TOL:
            return round(mid, 6)
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return round((lo + hi) / 2.0, 6)


def money_weighted_return(deposits: list, current_value: float,
                          as_of: datetime.date | None = None) -> dict | None:
    """Convenience wrapper: dated NET DEPOSITS plus today's book value.

    deposits: [(date, amount)] where a POSITIVE amount is money added to the
    portfolio (the natural way a human writes it). Sign is flipped internally
    to the XIRR convention.
    """
    if not deposits or not current_value:
        return None
    as_of = as_of or datetime.date.today()
    flows = [(d, -abs(a)) if a > 0 else (d, abs(a)) for d, a in deposits]
    flows.append((as_of, float(current_value)))
    rate = xirr(flows)
    if rate is None:
        return None
    invested = sum(a for _, a in deposits if a > 0)
    withdrawn = sum(-a for _, a in deposits if a < 0)
    first = min(d for d, _ in deposits)
    days = (as_of - first).days
    return {
        "mwr_annual_pct": round(rate * 100, 2),
        "net_invested": round(invested - withdrawn, 2),
        "current_value": round(float(current_value), 2),
        "first_flow": first.isoformat(),
        "as_of": as_of.isoformat(),
        "days": days,
        "n_flows": len(deposits),
        # Simple (non-annualised) gain on net contributed capital — the number
        # people actually picture. Only meaningful with no withdrawals.
        "simple_gain_pct": (round((current_value / (invested - withdrawn) - 1) * 100, 2)
                            if (invested - withdrawn) > 0 else None),
    }


def flows_from_snapshots(rows: list, materiality: float = 0.005) -> list:
    """FALLBACK when no broker transaction history is available: infer flows
    from cost-basis changes between portfolio snapshots.

    The FIRST flow is the opening VALUE, not a cost delta. The snapshot series
    starts mid-life, so the book already at work on day one is capital the
    owner has invested — omitting it makes MWR compute the return on only the
    later top-ups (here: $3.5k of deposits against a $15.9k book, an absurd
    apparent gain).

    This is a PROXY and weaker than real transactions — it cannot see a
    deposit that sat in cash, and it reads a sale as a negative flow of COST
    basis rather than proceeds. Prefer broker cash flow when available.
    """
    rows = rows or []
    if not rows:
        return []
    out = []
    try:
        out.append((datetime.date.fromisoformat(rows[0]["date"]),
                    float(rows[0].get("value_usd") or 0)))
    except (ValueError, KeyError, TypeError):
        return []
    for prev, cur in zip(rows, rows[1:]):
        delta = (cur.get("cost_usd") or 0) - (prev.get("cost_usd") or 0)
        base = cur.get("value_usd") or 0
        if base and abs(delta) > materiality * base:
            try:
                out.append((datetime.date.fromisoformat(cur["date"]), delta))
            except (ValueError, KeyError):
                continue
    return out
