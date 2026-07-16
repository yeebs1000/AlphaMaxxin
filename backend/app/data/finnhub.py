"""Finnhub provider: company news, basic fundamentals, earnings & IPO calendars.

Free tier: 60 req/min — every call goes through a shared token-bucket limiter
plus the disk cache. All methods degrade to None/[] without an API key.
Article dict shape matches the legacy news_fetcher.py exactly.
"""
import datetime
import os

from .base import (
    DiskTTLCache, RateLimiter, guard_online, http_get_json,
    relative_time as _relative_time,
    TTL_NEWS, TTL_FUNDAMENTALS, TTL_CALENDAR,
)

_BASE = "https://finnhub.io/api/v1"


class FinnhubProvider:
    name = "finnhub"

    def __init__(self, cache: DiskTTLCache, limiter: RateLimiter | None = None):
        self._cache = cache
        self._limiter = limiter or RateLimiter(55, 60.0)

    @property
    def api_key(self) -> str:
        return os.environ.get("FINNHUB_API_KEY", "").strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, params: str) -> dict | list | None:
        if not self.available:
            return None
        guard_online()  # outside the try — the offline tripwire must not be swallowed
        self._limiter.acquire()
        try:
            return http_get_json(f"{_BASE}/{path}?{params}&token={self.api_key}")
        except Exception:
            return None

    def news(self, ticker: str, days: int = 7) -> list[dict]:
        clean = ticker.replace(".SI", "").upper()
        key = f"{clean}:{days}"
        payload = self._cache.get_or_fetch("finnhub_news", key, TTL_NEWS,
                                           lambda: self._fetch_news(clean, days))
        return payload or []

    def _fetch_news(self, clean_ticker: str, days: int) -> list[dict] | None:
        today = datetime.date.today()
        start = (today - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        raw = self._get("company-news",
                        f"symbol={clean_ticker}&from={start}&to={today.strftime('%Y-%m-%d')}")
        if not isinstance(raw, list):
            return None
        articles = []
        for item in raw[:30]:
            headline = (item.get("headline") or "").strip()
            link = (item.get("url") or "").strip()
            if not headline or not link:
                continue
            articles.append({
                "title": headline,
                "url": link,
                "source": item.get("source", "Finnhub"),
                "published_epoch": item.get("datetime", 0),
                "published_rel": _relative_time(item.get("datetime", 0)),
                "ticker": clean_ticker,
                "summary": (item.get("summary") or "")[:300],
                "sentiment": "neutral",  # not on free tier
                "sentiment_score": 0.0,
                "provider": "finnhub",
            })
        articles.sort(key=lambda x: x["published_epoch"], reverse=True)
        return articles

    def metrics(self, ticker: str) -> dict | None:
        """Basic fundamentals from /stock/metric (metric=all). Fallback source
        when yfinance is unavailable."""
        clean = ticker.replace(".SI", "").upper()
        return self._cache.get_or_fetch("finnhub_metrics", clean, TTL_FUNDAMENTALS,
                                        lambda: self._get("stock/metric",
                                                          f"symbol={clean}&metric=all"))

    def earnings_calendar(self, from_date: str, to_date: str) -> list[dict]:
        """Upcoming earnings in [from_date, to_date] (YYYY-MM-DD). Returns
        [{date, symbol, epsEstimate, epsActual, hour, ...}]."""
        key = f"{from_date}:{to_date}"
        payload = self._cache.get_or_fetch(
            "finnhub_earnings", key, TTL_CALENDAR,
            lambda: self._get("calendar/earnings", f"from={from_date}&to={to_date}"))
        if isinstance(payload, dict):
            return payload.get("earningsCalendar", []) or []
        return []

    def insider_transactions(self, ticker: str) -> list[dict]:
        """Form-4 insider transactions (free tier). Rows: {name, share, change,
        filingDate, transactionDate, transactionCode, transactionPrice}."""
        clean = ticker.replace(".SI", "").upper()
        payload = self._cache.get_or_fetch(
            "finnhub_insiders", clean, TTL_FUNDAMENTALS,
            lambda: self._get("stock/insider-transactions", f"symbol={clean}"))
        if isinstance(payload, dict):
            return payload.get("data", []) or []
        return []

    def recommendation_trends(self, ticker: str) -> list[dict]:
        """Monthly analyst recommendation counts (free tier), newest first:
        [{period, strongBuy, buy, hold, sell, strongSell}]."""
        clean = ticker.replace(".SI", "").upper()
        payload = self._cache.get_or_fetch(
            "finnhub_rectrends", clean, TTL_FUNDAMENTALS,
            lambda: self._get("stock/recommendation", f"symbol={clean}"))
        return payload if isinstance(payload, list) else []

    def ipo_calendar(self, from_date: str, to_date: str) -> list[dict]:
        """Upcoming IPOs in [from_date, to_date]. Returns
        [{date, name, symbol, exchange, price, shares, status, ...}]."""
        key = f"{from_date}:{to_date}"
        payload = self._cache.get_or_fetch(
            "finnhub_ipos", key, TTL_CALENDAR,
            lambda: self._get("calendar/ipo", f"from={from_date}&to={to_date}"))
        if isinstance(payload, dict):
            return payload.get("ipoCalendar", []) or []
        return []
