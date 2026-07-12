"""Dividend income view of the book — trailing yield, yield-on-cost, and
imminent ex-dates per holding. Pure math over the yfinance dividends fetch;
tickers that pay nothing (or whose feed fails) are simply absent.
# ponytail: yfinance-only source; a moomoo variant exists in the broker client
# (get_moomoo_dividends) if HK/SG coverage ever proves thin — its row shape is
# unverified, which is why it isn't wired here yet.
"""
import datetime

EX_DATE_SOON_DAYS = 30


def income_view(holdings: list[dict], symbols: dict, quotes: dict, yfinance,
                today: datetime.date | None = None) -> dict:
    """{ticker: {ttm_dps, current_yield_pct, yield_on_cost_pct,
    ex_dividend_date, ex_date_soon}} for paying holdings, plus a portfolio
    rollup of soon ex-dates. Yields need same-currency price/cost — both are
    in the listing currency already."""
    today = today or datetime.date.today()
    if not yfinance.available:
        return {"by_ticker": {}, "ex_dates_soon": [], "feed_ok": False}
    out, soon = {}, []
    for h in holdings:
        ticker = h["ticker"]
        d = yfinance.dividends(symbols.get(ticker, ticker))
        if not d or not d.get("ttm_dps"):
            continue
        price = (quotes.get(ticker) or {}).get("price")
        cost = h.get("cost_price")
        entry = {
            "ttm_dps": d["ttm_dps"],
            "current_yield_pct": round(d["ttm_dps"] / price * 100, 2) if price else None,
            "yield_on_cost_pct": round(d["ttm_dps"] / cost * 100, 2) if cost else None,
            "ex_dividend_date": d.get("ex_dividend_date"),
            "ex_date_soon": False,
        }
        ex = d.get("ex_dividend_date")
        if ex:
            try:
                days = (datetime.date.fromisoformat(ex) - today).days
                if 0 <= days <= EX_DATE_SOON_DAYS:
                    entry["ex_date_soon"] = True
                    soon.append({"ticker": ticker, "ex_date": ex, "in_days": days})
            except ValueError:
                pass
        out[ticker] = entry
    soon.sort(key=lambda r: r["in_days"])
    return {"by_ticker": out, "ex_dates_soon": soon, "feed_ok": True}
