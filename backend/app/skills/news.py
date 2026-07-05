"""News digest — merge/dedupe/summarize articles from the providers into a
compact JSON block for the News/Catalysts analyst. Port of
news_fetcher.fetch_portfolio_news's merge logic, minus the fetching.
"""
from concurrent.futures import ThreadPoolExecutor


def merge_articles(per_ticker_articles: dict[str, list[dict]],
                   max_per_ticker: int = 5) -> list[dict]:
    """Merge {"AAPL": [articles...]} into one deduped list, newest first.
    Dedupe by URL and by the first 80 chars of the title (same rule as v1)."""
    merged: list[dict] = []
    seen_urls: set = set()
    seen_titles: set = set()
    for ticker, articles in per_ticker_articles.items():
        for art in articles[:max_per_ticker]:
            url = art.get("url", "")
            title_key = art.get("title", "")[:80].lower()
            if url and url not in seen_urls and title_key not in seen_titles:
                seen_urls.add(url)
                seen_titles.add(title_key)
                merged.append(art)
    merged.sort(key=lambda x: x.get("published_epoch", 0), reverse=True)
    return merged


def fetch_and_merge(registry, tickers: list[str], max_per_ticker: int = 5,
                    days: int = 7) -> list[dict]:
    """Fetch news for tickers from every available provider (Alpha Vantage
    preferred — it has sentiment — then Finnhub) and merge. Providers degrade
    to [] when unconfigured, so this works with any subset of keys.

    Per-ticker fetches run concurrently (matching v1's threading approach) —
    each provider's own rate limiter still caps total request rate, but a
    slow/rate-limited ticker no longer blocks every other ticker behind it
    in a strict queue, which is what made this take minutes for a full
    portfolio."""
    def fetch_one(ticker: str) -> list[dict]:
        articles: list[dict] = []
        if registry.alphavantage.available:
            articles.extend(registry.alphavantage.news(ticker)[:max_per_ticker])
        if registry.finnhub.available and len(articles) < max_per_ticker:
            articles.extend(
                registry.finnhub.news(ticker, days=days)[:max_per_ticker - len(articles)])
        return articles

    if not tickers:
        return []
    with ThreadPoolExecutor(max_workers=min(len(tickers), 10)) as pool:
        results = pool.map(fetch_one, tickers)
    per_ticker = dict(zip(tickers, results))
    return merge_articles(per_ticker, max_per_ticker=max_per_ticker)


def digest(articles: list[dict], max_items: int = 20) -> dict:
    """Compact JSON for the analyst: sentiment-rich articles prioritized
    (same rule as v1's format_news_for_llm), plus per-ticker sentiment
    aggregates."""
    def priority(a):
        return 0 if a.get("sentiment") in ("bullish", "bearish") else 1

    top = sorted(articles, key=lambda a: (priority(a), -a.get("published_epoch", 0)))[:max_items]
    items = [{
        "ticker": a.get("ticker", "?"),
        "headline": a.get("title", ""),
        "source": a.get("source", ""),
        "age": a.get("published_rel", "recently"),
        "sentiment": a.get("sentiment", "neutral"),
        "sentiment_score": a.get("sentiment_score", 0.0),
        "summary": a.get("summary", ""),
        "url": a.get("url", ""),
    } for a in top]

    by_ticker: dict[str, dict] = {}
    for a in articles:
        t = a.get("ticker", "?")
        agg = by_ticker.setdefault(t, {"count": 0, "score_sum": 0.0,
                                       "bullish": 0, "bearish": 0})
        agg["count"] += 1
        agg["score_sum"] += a.get("sentiment_score", 0.0)
        if a.get("sentiment") == "bullish":
            agg["bullish"] += 1
        elif a.get("sentiment") == "bearish":
            agg["bearish"] += 1
    sentiment_by_ticker = {
        t: {"count": v["count"],
            "avg_score": v["score_sum"] / v["count"] if v["count"] else 0.0,
            "bullish": v["bullish"], "bearish": v["bearish"]}
        for t, v in by_ticker.items()
    }
    return {"items": items, "sentiment_by_ticker": sentiment_by_ticker}
