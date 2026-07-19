"""Trading-calendar awareness: which market a ticker trades on, whether that
market is open right now, and its last trading day. Lets a report tag price
staleness ("HK closed — quotes as of Fri") and lets a scheduled run skip
markets that are shut.

MVP: regular weekly hours in each exchange's local timezone; weekends are
non-trading. Uses only the stdlib (zoneinfo) — no network, no dependency.
# ponytail: weekends + regular hours only, and lunch breaks are ignored
# (a market reads "open" straight through midday). Add per-exchange holiday
# tables (or akshare's trade-date calendar) and lunch sessions if the
# false-"open" cases actually bite a scheduled run.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# market code → (timezone, regular open, regular close) in exchange-local time.
_MARKETS = {
    "US": ("America/New_York", time(9, 30), time(16, 0)),
    "SG": ("Asia/Singapore", time(9, 0), time(17, 0)),
    "HK": ("Asia/Hong_Kong", time(9, 30), time(16, 0)),
    "JP": ("Asia/Tokyo", time(9, 0), time(15, 0)),
    "KR": ("Asia/Seoul", time(9, 0), time(15, 30)),
    "CN": ("Asia/Shanghai", time(9, 30), time(15, 0)),
}

# ticker suffix → market code. No suffix ⇒ US.
_SUFFIX_MARKET = {
    "SI": "SG", "HK": "HK", "T": "JP", "KS": "KR", "KQ": "KR",
    "SS": "CN", "SZ": "CN",
}


def market_of_ticker(ticker: str) -> str:
    """'9988.HK' → 'HK', 'D05.SI' → 'SG', 'AAPL' → 'US'."""
    if "." in ticker:
        return _SUFFIX_MARKET.get(ticker.rsplit(".", 1)[1].upper(), "US")
    return "US"


def _prev_weekday(d: date) -> date:
    while d.weekday() >= 5:  # Sat=5, Sun=6
        d -= timedelta(days=1)
    return d


def status(market: str, now: datetime | None = None) -> dict:
    """{market, tz, is_open, last_trading_day, as_of} for a market code.
    `now` (any tz-aware datetime) is for testing; defaults to real time."""
    tzname, open_t, close_t = _MARKETS.get(market, _MARKETS["US"])
    z = ZoneInfo(tzname)
    now = now.astimezone(z) if (now and now.tzinfo) else datetime.now(z)
    is_weekday = now.weekday() < 5
    is_open = is_weekday and open_t <= now.time() < close_t
    if is_weekday and now.time() >= open_t:
        last = now.date()                       # today's session has begun/ended
    else:
        last = _prev_weekday(now.date() - timedelta(days=1))
    return {"market": market, "tz": tzname, "is_open": is_open,
            "last_trading_day": last.isoformat(), "as_of": now.isoformat()}


def status_of_ticker(ticker: str, now: datetime | None = None) -> dict:
    return status(market_of_ticker(ticker), now=now)


def is_trading_day(market: str = "US", now: datetime | None = None) -> bool:
    """Weekday in the market's timezone — a non-trading-day guard for
    scheduled report runs.
    # ponytail: weekend check only; add holiday tables if it fires on holidays."""
    tzname = _MARKETS.get(market, _MARKETS["US"])[0]
    now = now.astimezone(ZoneInfo(tzname)) if (now and now.tzinfo) else datetime.now(ZoneInfo(tzname))
    return now.weekday() < 5


if __name__ == "__main__":
    from datetime import timezone
    # Sat 2026-07-04 12:00 UTC → every market closed, last day is Fri 07-03.
    sat = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    for m in _MARKETS:
        s = status(m, now=sat)
        assert s["is_open"] is False, m
        assert s["last_trading_day"] == "2026-07-03", (m, s["last_trading_day"])
    # Ticker routing.
    assert market_of_ticker("9988.HK") == "HK"
    assert market_of_ticker("D05.SI") == "SG"
    assert market_of_ticker("AAPL") == "US"
    # Wed 2026-07-08 14:00 NY → US open; 08:00 NY → US closed (pre-market).
    assert status("US", datetime(2026, 7, 8, 18, 0, tzinfo=timezone.utc))["is_open"] is True
    assert status("US", datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc))["is_open"] is False
    print("market_calendar self-check OK")
