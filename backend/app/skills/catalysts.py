"""Catalyst calendar — real upcoming earnings and IPOs from Finnhub's free
calendars. Replaces the LLM-recalled event guesses of the v1 Catalyst &
Event Calendar and IPO & Primary Markets agents with sourced dates."""
import datetime


def build_calendar(finnhub, tickers: list[str], horizon_days: int = 30,
                   today: datetime.date | None = None) -> dict:
    """{"events": [{date, ticker, type, detail}...] sorted by date,
    "upcoming_earnings_count", "source_available"}. Earnings are filtered to
    the given tickers; IPOs are market-wide."""
    today = today or datetime.date.today()
    to_date = today + datetime.timedelta(days=horizon_days)
    from_s, to_s = today.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d")

    if not finnhub.available:
        return {"events": [], "upcoming_earnings_count": 0, "source_available": False}

    wanted = {t.replace(".SI", "").upper() for t in tickers}
    events = []

    for row in finnhub.earnings_calendar(from_s, to_s):
        symbol = (row.get("symbol") or "").upper()
        if symbol not in wanted:
            continue
        detail = ""
        if row.get("epsEstimate") is not None:
            detail = f"EPS est {row['epsEstimate']}"
        if row.get("hour"):
            detail += f" ({row['hour']})"
        events.append({"date": row.get("date", ""), "ticker": symbol,
                       "type": "earnings", "detail": detail.strip()})

    for row in finnhub.ipo_calendar(from_s, to_s):
        name = row.get("name") or row.get("symbol") or "?"
        detail = ""
        if row.get("price"):
            detail = f"price {row['price']}"
        if row.get("exchange"):
            detail += f" on {row['exchange']}"
        events.append({"date": row.get("date", ""), "ticker": row.get("symbol") or "",
                       "type": "ipo", "detail": f"{name} {detail}".strip()})

    events.sort(key=lambda e: e["date"])
    return {
        "events": events,
        "upcoming_earnings_count": sum(1 for e in events if e["type"] == "earnings"),
        "source_available": True,
    }
