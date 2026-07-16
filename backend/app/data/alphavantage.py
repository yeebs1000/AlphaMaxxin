"""Alpha Vantage provider: news with per-ticker AI sentiment scores.

Free tier: 5 req/min — limiter + disk cache. Degrades to [] without a key.
Article dict shape matches the legacy news_fetcher.py exactly.
"""
import datetime
import os

from .base import (DiskTTLCache, RateLimiter, guard_online, http_get_json,
                   relative_time as _relative_time, TTL_NEWS)

_SENTIMENT_LABEL = {
    "Bullish": "bullish",
    "Somewhat-Bullish": "bullish",
    "Neutral": "neutral",
    "Somewhat-Bearish": "bearish",
    "Bearish": "bearish",
}


class AlphaVantageProvider:
    name = "alphavantage"

    def __init__(self, cache: DiskTTLCache, limiter: RateLimiter | None = None):
        self._cache = cache
        self._limiter = limiter or RateLimiter(5, 60.0)

    @property
    def api_key(self) -> str:
        return os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def news(self, ticker: str) -> list[dict]:
        if not self.available:
            return []
        clean = ticker.replace(".SI", "").upper()
        payload = self._cache.get_or_fetch("av_news", clean, TTL_NEWS,
                                           lambda: self._fetch_news(clean))
        return payload or []

    def _fetch_news(self, clean_ticker: str) -> list[dict] | None:
        guard_online()  # outside the try — the offline tripwire must not be swallowed
        self._limiter.acquire()
        try:
            data = http_get_json(
                "https://www.alphavantage.co/query"
                f"?function=NEWS_SENTIMENT&tickers={clean_ticker}"
                f"&sort=LATEST&limit=20&apikey={self.api_key}",
                timeout=12)
        except Exception:
            return None
        feed = data.get("feed", []) if isinstance(data, dict) else []
        articles = []
        for item in feed:
            headline = (item.get("title") or "").strip()
            link = (item.get("url") or "").strip()
            if not headline or not link:
                continue
            sentiment_raw = "neutral"
            sentiment_score = 0.0
            for ts in item.get("ticker_sentiment", []):
                if ts.get("ticker", "").upper() == clean_ticker:
                    sentiment_raw = _SENTIMENT_LABEL.get(
                        ts.get("ticker_sentiment_label", "Neutral"), "neutral")
                    try:
                        sentiment_score = float(ts.get("ticker_sentiment_score", 0))
                    except Exception:
                        sentiment_score = 0.0
                    break
            published_epoch = 0
            try:
                dt = datetime.datetime.strptime(
                    item.get("time_published", ""), "%Y%m%dT%H%M%S"
                ).replace(tzinfo=datetime.timezone.utc)
                published_epoch = int(dt.timestamp())
            except Exception:
                pass
            articles.append({
                "title": headline,
                "url": link,
                "source": item.get("source", "Alpha Vantage"),
                "published_epoch": published_epoch,
                "published_rel": _relative_time(published_epoch) if published_epoch else "recently",
                "ticker": clean_ticker,
                "summary": (item.get("summary") or "")[:300],
                "sentiment": sentiment_raw,
                "sentiment_score": sentiment_score,
                "provider": "alphavantage",
            })
        articles.sort(key=lambda x: x["published_epoch"], reverse=True)
        return articles
