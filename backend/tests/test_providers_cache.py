"""Unit tests for the data-layer plumbing: disk cache, rate limiter, and the
offline tripwire that guarantees tests can never hit the network."""
import pytest

from app.data.base import DiskTTLCache, OfflineError, RateLimiter, http_get_json, to_number
from app.data.yahoo import YahooProvider
from app.data.finnhub import FinnhubProvider
from app.data.fred import FredProvider


# ---------------------------------------------------------------------------
# to_number — the shared boundary coercion that keeps a non-numeric provider
# value ("Infinity", "NM", None, a bool) from ever reaching a numeric
# comparison downstream and crashing it.
# ---------------------------------------------------------------------------
def test_to_number_passes_real_numbers():
    assert to_number(42) == 42.0
    assert to_number(3.14) == 3.14
    assert to_number(-1.5) == -1.5
    assert to_number(0) == 0.0
    assert to_number("27.66") == 27.66      # numeric-looking string still parses
    assert to_number("-3") == -3.0


def test_to_number_rejects_non_finite_and_junk():
    for junk in ("Infinity", "-Infinity", "NaN", "NM", "N/A", "", "abc",
                 None, True, False, [], {}, float("inf"), float("nan")):
        assert to_number(junk) is None, junk


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# ---------------------------------------------------------------------------
# DiskTTLCache
# ---------------------------------------------------------------------------
def test_cache_miss_then_hit(tmp_path):
    clock = FakeClock()
    cache = DiskTTLCache(root=tmp_path, clock=clock)
    assert cache.get("ns", "key") is None
    cache.put("ns", "key", {"a": 1}, ttl_s=60)
    assert cache.get("ns", "key") == {"a": 1}


def test_cache_expires_after_ttl(tmp_path):
    clock = FakeClock()
    cache = DiskTTLCache(root=tmp_path, clock=clock)
    cache.put("ns", "key", [1, 2, 3], ttl_s=60)
    clock.advance(59)
    assert cache.get("ns", "key") == [1, 2, 3]
    clock.advance(2)  # now 61s old
    assert cache.get("ns", "key") is None


def test_cache_get_or_fetch_only_fetches_on_miss(tmp_path):
    clock = FakeClock()
    cache = DiskTTLCache(root=tmp_path, clock=clock)
    calls = []

    def fetch():
        calls.append(1)
        return "payload"

    assert cache.get_or_fetch("ns", "k", 60, fetch) == "payload"
    assert cache.get_or_fetch("ns", "k", 60, fetch) == "payload"
    assert len(calls) == 1  # second call served from disk


def test_cache_does_not_store_none(tmp_path):
    cache = DiskTTLCache(root=tmp_path, clock=FakeClock())
    calls = []

    def fetch():
        calls.append(1)
        return None

    assert cache.get_or_fetch("ns", "k", 60, fetch) is None
    assert cache.get_or_fetch("ns", "k", 60, fetch) is None
    assert len(calls) == 2  # failed fetches are retried, not cached


def test_cache_keys_do_not_collide(tmp_path):
    cache = DiskTTLCache(root=tmp_path, clock=FakeClock())
    cache.put("ns", "key1", "v1", 60)
    cache.put("ns", "key2", "v2", 60)
    cache.put("other", "key1", "v3", 60)
    assert cache.get("ns", "key1") == "v1"
    assert cache.get("ns", "key2") == "v2"
    assert cache.get("other", "key1") == "v3"


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------
def test_rate_limiter_allows_burst_up_to_limit():
    clock = FakeClock()
    sleeps = []
    limiter = RateLimiter(3, 60.0, clock=clock, sleeper=sleeps.append)
    for _ in range(3):
        limiter.acquire()
    assert sleeps == []  # burst within limit never sleeps


def test_rate_limiter_sleeps_when_window_full():
    clock = FakeClock()
    sleeps = []

    def sleeper(seconds):
        sleeps.append(seconds)
        clock.advance(seconds)  # simulate real sleep

    limiter = RateLimiter(2, 60.0, clock=clock, sleeper=sleeper)
    limiter.acquire()
    clock.advance(10)
    limiter.acquire()
    limiter.acquire()  # window full — must wait until the first stamp ages out
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(50.0)


def test_rate_limiter_window_slides():
    clock = FakeClock()
    sleeps = []
    limiter = RateLimiter(2, 60.0, clock=clock, sleeper=sleeps.append)
    limiter.acquire()
    limiter.acquire()
    clock.advance(61)  # both stamps expired
    limiter.acquire()
    assert sleeps == []


# ---------------------------------------------------------------------------
# Offline tripwire — ALPHAMAXXIN_OFFLINE=1 is set for the whole suite in
# conftest.py; any attempted fetch must raise, never silently return None.
# ---------------------------------------------------------------------------
def test_http_get_json_raises_offline():
    with pytest.raises(OfflineError):
        http_get_json("https://example.com/anything")


def test_yahoo_provider_raises_offline(tmp_path):
    provider = YahooProvider(DiskTTLCache(root=tmp_path))
    with pytest.raises(OfflineError):
        provider.ohlcv("AAPL")
    with pytest.raises(OfflineError):
        provider.quote("AAPL")
    with pytest.raises(OfflineError):
        provider.search("apple")
    with pytest.raises(OfflineError):
        provider.fx_rate("SGD")


def test_finnhub_provider_raises_offline_when_key_set(tmp_path, monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key-not-real")
    provider = FinnhubProvider(DiskTTLCache(root=tmp_path))
    with pytest.raises(OfflineError):
        provider.news("AAPL")


def test_finnhub_provider_degrades_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    provider = FinnhubProvider(DiskTTLCache(root=tmp_path))
    assert provider.news("AAPL") == []          # no key → empty, no fetch
    assert provider.metrics("AAPL") is None
    assert provider.earnings_calendar("2026-07-01", "2026-07-14") == []


def test_fred_provider_raises_offline(tmp_path, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    provider = FredProvider(DiskTTLCache(root=tmp_path))
    with pytest.raises(OfflineError):
        provider.series("DGS10")


def test_cached_payloads_are_served_offline(tmp_path):
    """A warm cache works even offline — only the fetch path is guarded."""
    cache = DiskTTLCache(root=tmp_path)
    provider = YahooProvider(cache)
    cache.put("yahoo_quote", "AAPL", {"price": 123.0}, ttl_s=3600)
    assert provider.quote("AAPL") == {"price": 123.0}
