"""Shared plumbing for data providers: offline guard, disk cache, rate limiter.

Every real provider must call `guard_online()` before touching the network.
With ALPHAMAXXIN_OFFLINE=1 set (as it is for the whole test suite and CI),
that raises OfflineError — the tripwire that enforces the project rule that
development and testing never call live APIs.
"""
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import requests


class OfflineError(RuntimeError):
    """Raised when code attempts a network fetch while ALPHAMAXXIN_OFFLINE=1."""


def guard_online() -> None:
    if os.environ.get("ALPHAMAXXIN_OFFLINE") == "1":
        raise OfflineError(
            "Network fetch attempted while ALPHAMAXXIN_OFFLINE=1 — tests must "
            "use fixtures/fakes, never live providers."
        )


def to_number(value: Any) -> float | None:
    """Best-effort numeric coercion for anything crossing a provider
    boundary (yfinance, Finnhub, FRED, moomoo, cached JSON). Real-world
    providers occasionally hand back a non-numeric sentinel instead of a
    plain number or None — yfinance's .info dict can literally contain the
    Python string "Infinity" for an undefined ratio (e.g. P/E with negative
    earnings); Finnhub's free tier can emit "NM"/"N/A" strings the same way.

    Returns a plain float for anything that parses to a *finite* number,
    else None — bools, unparseable strings, and inf/nan (float("Infinity")
    parses without error but is exactly as useless as the string was) all
    become None, so a bad upstream value degrades to "missing data" instead
    of reaching a numeric comparison somewhere downstream and crashing it.
    Every skill that reads an externally-sourced numeric field should pass
    it through this — the fix belongs at the boundary, not scattered across
    every comparison site."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        try:
            num = float(value)
        except ValueError:
            return None
    else:
        return None
    if num != num or num in (float("inf"), float("-inf")):  # NaN / Infinity
        return None
    return num


def relative_time(epoch: float) -> str:
    """'2h ago'-style age for a unix timestamp — shared by news providers."""
    import datetime
    try:
        then = datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
        diff = int((datetime.datetime.now(tz=datetime.timezone.utc) - then).total_seconds())
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return "recently"


_DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def http_get_json(url: str, timeout: float = 8.0, headers: dict | None = None) -> Any:
    # requests, not urllib — bare urllib.request gets its connection reset or
    # times out against some providers (confirmed against fred.stlouisfed.org:
    # a WAF/CDN in front of it evidently fingerprints and blocks urllib's raw
    # TLS handshake while requests' works fine with an identical URL/timeout).
    # Every caller already wraps these in `except Exception`, so the swapped
    # exception types (requests.RequestException vs urllib's) need no changes.
    guard_online()
    resp = requests.get(url, headers=headers or _DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def http_get_text(url: str, timeout: float = 8.0, headers: dict | None = None) -> str:
    guard_online()
    resp = requests.get(url, headers=headers or _DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def default_cache_root() -> Path:
    """Cache lives OUTSIDE the repo (which sits in a OneDrive-synced folder —
    heavy small-file churn there thrashes the sync client)."""
    override = os.environ.get("ALPHAMAXXIN_CACHE_DIR")
    if override:
        return Path(override)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "AlphaMaxxin" / "cache"
    return Path.home() / ".cache" / "alphamaxxin"


class DiskTTLCache:
    """JSON-payload disk cache. Entries live at {root}/{namespace}/{sha1(key)}.json
    as {"fetched_at": epoch, "ttl_s": n, "key": k, "payload": ...}."""

    def __init__(self, root: Path | None = None, clock: Callable[[], float] = time.time):
        self.root = Path(root) if root else default_cache_root()
        self._clock = clock

    def _path(self, namespace: str, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.root / namespace / f"{digest}.json"

    def get(self, namespace: str, key: str) -> Any | None:
        path = self._path(namespace, key)
        try:
            with open(path, "r", encoding="utf-8") as f:
                entry = json.load(f)
        except (OSError, ValueError):
            return None
        if self._clock() - entry.get("fetched_at", 0) > entry.get("ttl_s", 0):
            return None
        return entry.get("payload")

    def put(self, namespace: str, key: str, payload: Any, ttl_s: int) -> None:
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"fetched_at": self._clock(), "ttl_s": ttl_s, "key": key, "payload": payload}
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entry, f)
        os.replace(tmp, path)

    def get_or_fetch(self, namespace: str, key: str, ttl_s: int, fetch: Callable[[], Any]) -> Any:
        cached = self.get(namespace, key)
        if cached is not None:
            return cached
        payload = fetch()
        if payload is not None:
            self.put(namespace, key, payload, ttl_s)
        return payload


# Standard TTLs (seconds) — see plan: quotes 5m, OHLCV 6h, fundamentals 24h,
# FRED/calendars 12h, news 5m.
TTL_QUOTE = 300
TTL_NEWS = 300
TTL_OHLCV = 6 * 3600
TTL_FUNDAMENTALS = 24 * 3600
TTL_STATEMENTS = 30 * 86400  # annual statements move quarterly at most
TTL_UNIVERSE = 30 * 86400    # index constituents change a few times a year
TTL_MACRO = 12 * 3600
TTL_CALENDAR = 12 * 3600


class RateLimiter:
    """Blocking token bucket: at most `max_calls` per `per_seconds` window.
    Thread-safe — providers are now called from a thread pool (news fetches
    run one thread per ticker) and share one limiter instance per provider."""

    def __init__(self, max_calls: int, per_seconds: float,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self._clock = clock
        self._sleeper = sleeper
        self._stamps: list[float] = []
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            cutoff = now - self.per_seconds
            self._stamps = [s for s in self._stamps if s > cutoff]
            if len(self._stamps) >= self.max_calls:
                wait = self._stamps[0] + self.per_seconds - now
                if wait > 0:
                    self._sleeper(wait)
                    now = self._clock()
                    cutoff = now - self.per_seconds
                    self._stamps = [s for s in self._stamps if s > cutoff]
            self._stamps.append(self._clock())
