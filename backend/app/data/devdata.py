"""Developer-footprint feeds — GitHub, npm, PyPI (pypistats.org), Docker Hub.
All official and keyless; a free GITHUB_TOKEN in .env raises GitHub's rate
limit from 60 to 5,000 req/hr. Every fetch is disk-cached and offline-guarded;
failures degrade to None per source, never crash a run.
"""
import os

from .base import DiskTTLCache, guard_online, http_get_json, TTL_FUNDAMENTALS

_cache = DiskTTLCache()


def _get(url: str, headers: dict | None = None):
    guard_online()
    try:
        return http_get_json(url, headers=headers)
    except Exception:
        return None


def _github_headers() -> dict:
    h = {"User-Agent": "AlphaMaxxin", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def github_repo(owner_repo: str) -> dict | None:
    """{stars, forks, commits_13w, commits_prior_13w} for one repo. Commit
    counts come from the participation endpoint's 52 weekly buckets."""
    def fetch():
        base = f"https://api.github.com/repos/{owner_repo}"
        repo = _get(base, headers=_github_headers())
        if not repo or "stargazers_count" not in repo:
            return None
        part = _get(f"{base}/stats/participation", headers=_github_headers()) or {}
        weeks = part.get("all") or []
        return {"stars": repo["stargazers_count"], "forks": repo["forks_count"],
                "commits_13w": sum(weeks[-13:]) if len(weeks) >= 13 else None,
                "commits_prior_13w": sum(weeks[-26:-13]) if len(weeks) >= 26 else None}
    return _cache.get_or_fetch("github_repo", owner_repo, TTL_FUNDAMENTALS, fetch)


def npm_downloads(package: str) -> dict | None:
    """{last_month, prior_month} download counts."""
    def fetch():
        cur = _get(f"https://api.npmjs.org/downloads/point/last-month/{package}")
        if not cur or "downloads" not in cur:
            return None
        import datetime
        end = datetime.date.today() - datetime.timedelta(days=30)
        start = end - datetime.timedelta(days=30)
        prior = _get("https://api.npmjs.org/downloads/point/"
                     f"{start.isoformat()}:{end.isoformat()}/{package}") or {}
        return {"last_month": cur["downloads"], "prior_month": prior.get("downloads")}
    return _cache.get_or_fetch("npm_dl", package, TTL_FUNDAMENTALS, fetch)


def pypi_downloads(package: str) -> dict | None:
    """{last_month} downloads via pypistats.org's recent endpoint."""
    def fetch():
        data = _get(f"https://pypistats.org/api/packages/{package}/recent")
        month = (data or {}).get("data", {}).get("last_month")
        return {"last_month": month} if month is not None else None
    return _cache.get_or_fetch("pypi_dl", package, TTL_FUNDAMENTALS, fetch)


def docker_pulls(namespace_repo: str) -> dict | None:
    """{pulls} — cumulative pull count (Docker Hub exposes no rate)."""
    def fetch():
        data = _get(f"https://hub.docker.com/v2/repositories/{namespace_repo}/")
        pulls = (data or {}).get("pull_count")
        return {"pulls": pulls} if pulls is not None else None
    return _cache.get_or_fetch("docker_pulls", namespace_repo, TTL_FUNDAMENTALS, fetch)
