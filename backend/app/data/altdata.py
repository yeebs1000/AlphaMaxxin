"""Alternative-data feeds — attention & demand proxies from official keyless
APIs: Wikipedia pageviews (WMF REST), iTunes app stats (lookup API), and
Greenhouse public job boards (hiring velocity). Disk-cached, offline-guarded,
per-source degradation.

Google Trends is deliberately NOT here: the only access path is the
unofficial pytrends scraper, which Google rate-limits and breaks regularly —
a flaky dependency isn't worth one more attention proxy. Revisit if an
official API ever appears.
"""
import datetime

from .base import DiskTTLCache, guard_online, http_get_json, TTL_FUNDAMENTALS

_cache = DiskTTLCache()
# WMF etiquette asks for an identifying UA on their REST API.
_WIKI_UA = {"User-Agent": "AlphaMaxxin/2.0 (personal research tool)"}


def _get(url: str, headers: dict | None = None):
    guard_online()
    try:
        return http_get_json(url, headers=headers)
    except Exception:
        return None


def wiki_pageviews(article: str) -> dict | None:
    """{last_30d, prior_30d, growth_pct} daily-summed views for one article."""
    def fetch():
        end = datetime.date.today() - datetime.timedelta(days=1)
        start = end - datetime.timedelta(days=59)
        url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
               f"en.wikipedia/all-access/user/{article.replace(' ', '_')}/daily/"
               f"{start:%Y%m%d}/{end:%Y%m%d}")
        data = _get(url, headers=_WIKI_UA)
        items = (data or {}).get("items") or []
        if len(items) < 40:
            return None
        views = [i.get("views", 0) for i in items]
        prior, last = sum(views[:30]), sum(views[-30:])
        return {"last_30d": last, "prior_30d": prior,
                "growth_pct": round((last - prior) / prior * 100, 1) if prior else None}
    return _cache.get_or_fetch("wiki_views", article, TTL_FUNDAMENTALS, fetch)


def itunes_app(app_id: int) -> dict | None:
    """{name, rating, rating_count} — cumulative counts (no free history)."""
    def fetch():
        data = _get(f"https://itunes.apple.com/lookup?id={app_id}")
        results = (data or {}).get("results") or []
        if not results:
            return None
        r = results[0]
        return {"name": r.get("trackName"),
                "rating": r.get("averageUserRating"),
                "rating_count": r.get("userRatingCount")}
    return _cache.get_or_fetch("itunes_app", str(app_id), TTL_FUNDAMENTALS, fetch)


def greenhouse_jobs(board: str) -> dict | None:
    """{open_roles} on a company's public Greenhouse board."""
    def fetch():
        data = _get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
        jobs = (data or {}).get("jobs")
        return {"open_roles": len(jobs)} if jobs is not None else None
    return _cache.get_or_fetch("greenhouse", board, TTL_FUNDAMENTALS, fetch)
