"""akshare fallback — symbol mapping, market gating, offline-tripwire respect,
and the live_quote/live_ohlcv fall-through routing. The real DataFrame parse is
online-only (blocked by the tripwire), so it's validated by a live fetch, not
here."""
import pytest

from app.data import akshare_provider as aks
from app.data import live_quote
from app.data.base import OfflineError
from .fakes import FakeYahoo


def test_code_mapping():
    assert aks._code("9988.HK", "HK") == "09988"   # HK → 5-digit zero-padded
    assert aks._code("0700.HK", "HK") == "00700"
    assert aks._code("600519.SS", "CN") == "600519"
    assert aks._code("000001.SZ", "CN") == "000001"


def test_ohlcv_gates_non_cn_hk_before_any_fetch(monkeypatch):
    # Pretend akshare is installed; a US ticker must return None WITHOUT tripping
    # guard_online (wrong market, nothing to fetch).
    monkeypatch.setattr(aks, "_ak", lambda: object())
    assert aks.ohlcv("AAPL", "1d") is None


def test_ohlcv_respects_offline_tripwire_for_hk(monkeypatch):
    monkeypatch.setattr(aks, "_ak", lambda: object())
    with pytest.raises(OfflineError):        # HK/CN path must hit guard_online
        aks.ohlcv("9988.HK", "1d")


def test_available_reflects_module_presence(monkeypatch):
    monkeypatch.setattr(aks, "_ak", lambda: None)
    assert aks.available() is False
    monkeypatch.setattr(aks, "_ak", lambda: object())
    assert aks.available() is True


def test_live_quote_falls_through_to_akshare(monkeypatch):
    # Yahoo has nothing for this HK name; akshare supplies it as last resort.
    monkeypatch.setattr(aks, "available", lambda: True)
    monkeypatch.setattr(aks, "quote", lambda t: {"price": 9.0, "currency": "HKD"})
    q = live_quote.live_quote("9988.HK", FakeYahoo())
    assert q == {"price": 9.0, "currency": "HKD"}


def test_live_ohlcv_falls_through_to_akshare(monkeypatch):
    monkeypatch.setattr(aks, "available", lambda: True)
    monkeypatch.setattr(aks, "ohlcv",
                        lambda t, interval: {"closes": [1.0], "highs": [1], "lows": [1], "volumes": [1]})
    bars = live_quote.live_ohlcv("600519.SS", FakeYahoo(), "1d")
    assert bars["closes"] == [1.0]
