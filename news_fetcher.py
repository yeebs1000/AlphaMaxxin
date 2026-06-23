"""
AlphaMaxxin — News Intelligence Layer
Fetches real-time financial news for portfolio holdings from:
  1. Finnhub  (FINNHUB_API_KEY)   — per-ticker company news, 60 req/min free
  2. Alpha Vantage (ALPHAVANTAGE_API_KEY) — news + AI sentiment scores
  3. Yahoo Finance RSS              — zero-key fallback

All sources are optional; the system gracefully degrades to whatever is available.
"""
import os
import json
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import threading
import time

# ── Simple in-process cache (avoids hammering APIs on every agent call) ──────
_news_cache: dict = {}          # { cache_key: (timestamp, articles) }
_CACHE_TTL = 300                 # seconds — refresh every 5 minutes


def _now_ts() -> float:
    return time.monotonic()


def _cache_get(key: str):
    entry = _news_cache.get(key)
    if entry and (_now_ts() - entry[0]) < _CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value):
    _news_cache[key] = (_now_ts(), value)


# ── HTTP helper ───────────────────────────────────────────────────────────────
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AlphaMaxxin/2.3)"}


def _http_get(url: str, timeout: int = 8) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


# ── Relative time formatter ───────────────────────────────────────────────────
def _relative_time(epoch_or_iso) -> str:
    """Convert epoch timestamp or ISO string to a human-readable relative time."""
    try:
        if isinstance(epoch_or_iso, (int, float)):
            then = datetime.datetime.fromtimestamp(epoch_or_iso, tz=datetime.timezone.utc)
        else:
            then = datetime.datetime.fromisoformat(str(epoch_or_iso).replace("Z", "+00:00"))
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        diff = int((now - then).total_seconds())
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return "recently"


# =============================================================================
# Source 1 — Finnhub
# =============================================================================
def fetch_finnhub_news(ticker: str, days: int = 7) -> list[dict]:
    """
    Fetch company news from Finnhub for the given ticker.
    Returns list of article dicts: {title, url, source, published_at, ticker, sentiment, summary}
    """
    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not api_key:
        return []

    cache_key = f"finnhub_{ticker}_{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    today = datetime.date.today()
    start = (today - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    # Clean ticker for Finnhub (strip exchange suffix)
    clean_ticker = ticker.replace(".SI", "").upper()

    url = (
        f"https://finnhub.io/api/v1/company-news"
        f"?symbol={clean_ticker}&from={start}&to={end}&token={api_key}"
    )
    raw = _http_get(url)
    if not raw:
        return []

    try:
        articles_raw = json.loads(raw)
        if not isinstance(articles_raw, list):
            return []
    except Exception:
        return []

    articles = []
    for item in articles_raw[:30]:  # cap at 30 to avoid noise
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
            "sentiment": "neutral",   # Finnhub doesn't provide sentiment on free tier
            "sentiment_score": 0.0,
            "provider": "finnhub",
        })

    # Sort newest-first
    articles.sort(key=lambda x: x["published_epoch"], reverse=True)
    _cache_set(cache_key, articles)
    return articles


# =============================================================================
# Source 2 — Alpha Vantage (News + Sentiment)
# =============================================================================
_SENTIMENT_LABEL = {
    "Bullish": "bullish",
    "Somewhat-Bullish": "bullish",
    "Neutral": "neutral",
    "Somewhat-Bearish": "bearish",
    "Bearish": "bearish",
}


def fetch_alphavantage_news(ticker: str) -> list[dict]:
    """
    Fetch news + AI sentiment scores from Alpha Vantage NEWS_SENTIMENT endpoint.
    Returns list of article dicts with sentiment scores.
    """
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if not api_key:
        return []

    cache_key = f"av_{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    clean_ticker = ticker.replace(".SI", "").upper()

    url = (
        f"https://www.alphavantage.co/query"
        f"?function=NEWS_SENTIMENT&tickers={clean_ticker}"
        f"&sort=LATEST&limit=20&apikey={api_key}"
    )
    raw = _http_get(url, timeout=12)
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except Exception:
        return []

    feed = data.get("feed", [])
    if not feed:
        return []

    articles = []
    for item in feed:
        headline = (item.get("title") or "").strip()
        link = (item.get("url") or "").strip()
        if not headline or not link:
            continue

        # Extract per-ticker sentiment
        sentiment_raw = "neutral"
        sentiment_score = 0.0
        for ts in item.get("ticker_sentiment", []):
            if ts.get("ticker", "").upper() == clean_ticker:
                sentiment_raw = _SENTIMENT_LABEL.get(ts.get("ticker_sentiment_label", "Neutral"), "neutral")
                try:
                    sentiment_score = float(ts.get("ticker_sentiment_score", 0))
                except Exception:
                    sentiment_score = 0.0
                break

        # Parse time: "20240115T143000"
        raw_time = item.get("time_published", "")
        published_epoch = 0
        try:
            dt = datetime.datetime.strptime(raw_time, "%Y%m%dT%H%M%S").replace(
                tzinfo=datetime.timezone.utc
            )
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
    _cache_set(cache_key, articles)
    return articles


# =============================================================================
# Source 3 — Yahoo Finance RSS (zero-key fallback)
# =============================================================================
def fetch_yahoo_rss_news(ticker: str) -> list[dict]:
    """
    Parse Yahoo Finance RSS feed for the given ticker.
    No API key required — useful as a fallback.
    """
    cache_key = f"yahoo_rss_{ticker}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    clean_ticker = ticker.replace(".SI", "").upper()
    encoded = urllib.parse.quote(clean_ticker)
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={encoded}&region=US&lang=en-US"
    raw = _http_get(url)
    if not raw:
        return []

    articles = []
    try:
        root = ET.fromstring(raw.decode("utf-8", errors="replace"))
        ns = {"dc": "http://purl.org/dc/elements/1.1/"}
        for item in root.iter("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            desc_el = item.find("description")

            title = (title_el.text or "").strip() if title_el is not None else ""
            link = (link_el.text or "").strip() if link_el is not None else ""
            if not title or not link:
                continue

            published_epoch = 0
            if pub_el is not None and pub_el.text:
                try:
                    from email.utils import parsedate_to_datetime
                    published_epoch = int(parsedate_to_datetime(pub_el.text).timestamp())
                except Exception:
                    pass

            summary = ""
            if desc_el is not None and desc_el.text:
                summary = desc_el.text.strip()[:300]

            articles.append({
                "title": title,
                "url": link,
                "source": "Yahoo Finance",
                "published_epoch": published_epoch,
                "published_rel": _relative_time(published_epoch) if published_epoch else "recently",
                "ticker": clean_ticker,
                "summary": summary,
                "sentiment": "neutral",
                "sentiment_score": 0.0,
                "provider": "yahoo_rss",
            })
    except Exception:
        pass

    articles.sort(key=lambda x: x["published_epoch"], reverse=True)
    _cache_set(cache_key, articles)
    return articles


# =============================================================================
# Orchestrator — fetch for multiple tickers, deduplicate
# =============================================================================
def fetch_portfolio_news(
    tickers: list[str],
    max_per_ticker: int = 5,
    days: int = 7,
) -> list[dict]:
    """
    Fetch news for a list of tickers using all available sources.
    Deduplicates by URL. Returns merged list sorted by recency.

    Args:
        tickers: List of ticker symbols (e.g. ["AAPL", "MSFT", "D05"])
        max_per_ticker: Max articles to include per ticker
        days: Lookback window in days for Finnhub

    Returns:
        List of unified article dicts, sorted newest-first.
    """
    all_articles: list[dict] = []
    seen_urls: set = set()
    seen_titles: set = set()

    has_finnhub = bool(os.environ.get("FINNHUB_API_KEY", "").strip())
    has_av = bool(os.environ.get("ALPHAVANTAGE_API_KEY", "").strip())

    results_by_ticker: dict[str, list] = {}

    def fetch_one(ticker):
        articles = []
        # Prefer Alpha Vantage (has sentiment) then Finnhub then Yahoo
        if has_av:
            av_arts = fetch_alphavantage_news(ticker)
            articles.extend(av_arts[:max_per_ticker])
        if has_finnhub and len(articles) < max_per_ticker:
            fh_arts = fetch_finnhub_news(ticker, days=days)
            articles.extend(fh_arts[:max_per_ticker - len(articles)])
        if len(articles) < 2:
            # Always try Yahoo as supplemental fallback
            yf_arts = fetch_yahoo_rss_news(ticker)
            articles.extend(yf_arts[:max_per_ticker - len(articles)])
        results_by_ticker[ticker] = articles

    # Fetch all tickers concurrently (use threads to avoid blocking asyncio)
    threads = [threading.Thread(target=fetch_one, args=(t,), daemon=True) for t in tickers]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=15)  # 15s max per fetch round

    # Merge and deduplicate
    for ticker in tickers:
        for art in results_by_ticker.get(ticker, []):
            url = art.get("url", "")
            title_key = art.get("title", "")[:80].lower()
            if url and url not in seen_urls and title_key not in seen_titles:
                seen_urls.add(url)
                seen_titles.add(title_key)
                all_articles.append(art)

    # Sort all by recency
    all_articles.sort(key=lambda x: x.get("published_epoch", 0), reverse=True)
    return all_articles


# =============================================================================
# LLM context formatter
# =============================================================================
def format_news_for_llm(articles: list[dict], max_articles: int = 20) -> str:
    """
    Format a list of news articles into a compact text block for LLM injection.
    Prioritises bullish/bearish articles over neutral for signal richness.
    """
    if not articles:
        return "No recent news articles available from configured sources."

    # Prioritise sentiment-rich articles
    def priority(a):
        s = a.get("sentiment", "neutral")
        if s in ("bullish", "bearish"):
            return 0
        return 1

    sorted_arts = sorted(articles, key=lambda a: (priority(a), -a.get("published_epoch", 0)))
    top = sorted_arts[:max_articles]

    lines = []
    for i, art in enumerate(top, 1):
        ticker = art.get("ticker", "?")
        title = art.get("title", "No title")
        source = art.get("source", "Unknown")
        rel_time = art.get("published_rel", "recently")
        sentiment = art.get("sentiment", "neutral")
        score = art.get("sentiment_score", 0.0)
        url = art.get("url", "")
        summary = art.get("summary", "")

        sentiment_tag = {
            "bullish": "📈 BULLISH",
            "bearish": "📉 BEARISH",
            "neutral": "➖ NEUTRAL",
        }.get(sentiment, "➖ NEUTRAL")

        if score != 0.0:
            sentiment_tag += f" ({score:+.2f})"

        line = (
            f"{i}. [{ticker}] {title}\n"
            f"   Source: {source} | {rel_time} | {sentiment_tag}\n"
        )
        if summary:
            line += f"   Summary: {summary}\n"
        if url:
            line += f"   Link: {url}\n"
        lines.append(line)

    return "\n".join(lines)


# =============================================================================
# Convenience: get news for the portfolio and return formatted block
# =============================================================================
def get_news_context_for_portfolio(tickers: list[str], max_articles: int = 20) -> str:
    """
    High-level helper: fetch + format news for a list of tickers.
    Returns a pre-formatted string ready to embed in the LLM context.
    """
    if not tickers:
        return "No tickers provided."
    articles = fetch_portfolio_news(tickers, max_per_ticker=5)
    return format_news_for_llm(articles, max_articles=max_articles)
