"""Alt-data + digital-footprint skills: curated-map coverage, degradation,
offline tripwire on the providers."""
import pytest

from app.data import altdata, devdata
from app.data.base import OfflineError
from app.skills import alt_data, digital_footprint


def test_providers_respect_offline_tripwire():
    with pytest.raises(OfflineError):
        altdata._get("https://example.test/x")
    with pytest.raises(OfflineError):
        devdata._get("https://example.test/x")


def test_alt_data_collect_with_fake_providers(monkeypatch):
    monkeypatch.setattr(altdata, "wiki_pageviews",
                        lambda a: {"last_30d": 5000, "prior_30d": 4000, "growth_pct": 25.0})
    monkeypatch.setattr(altdata, "itunes_app",
                        lambda i: {"name": "Grab", "rating": 4.7, "rating_count": 1_000_000})
    monkeypatch.setattr(altdata, "greenhouse_jobs", lambda b: {"open_roles": 120})
    out = alt_data.collect(["DUOL", "MSFT", "ZZZZ"])
    assert out["by_ticker"]["DUOL"]["wiki_views"]["growth_pct"] == 25.0
    assert out["by_ticker"]["DUOL"]["app"]["rating_count"] == 1_000_000
    assert out["by_ticker"]["DUOL"]["jobs"]["open_roles"] == 120
    assert "wiki_views" in out["by_ticker"]["MSFT"]
    assert "app" not in out["by_ticker"]["MSFT"]      # no app mapped for MSFT
    assert out["not_covered"] == ["ZZZZ"]


def test_alt_data_all_sources_down_means_not_covered(monkeypatch):
    monkeypatch.setattr(altdata, "wiki_pageviews", lambda a: None)
    monkeypatch.setattr(altdata, "itunes_app", lambda i: None)
    monkeypatch.setattr(altdata, "greenhouse_jobs", lambda b: None)
    out = alt_data.collect(["GRAB"])
    assert out["by_ticker"] == {} and out["not_covered"] == ["GRAB"]


def test_footprint_collect_with_fake_providers(monkeypatch):
    monkeypatch.setattr(devdata, "github_repo",
                        lambda r: {"stars": 90000, "forks": 8000,
                                   "commits_13w": 400, "commits_prior_13w": 500})
    monkeypatch.setattr(devdata, "npm_downloads",
                        lambda p: {"last_month": 1_000_000, "prior_month": 900_000})
    monkeypatch.setattr(devdata, "pypi_downloads", lambda p: {"last_month": 5_000_000})
    monkeypatch.setattr(devdata, "docker_pulls", lambda p: {"pulls": 10_000_000})
    out = digital_footprint.collect(["META", "SMCI"])
    meta = out["by_ticker"]["META"]
    assert meta["github"]["facebook/react"]["stars"] == 90000
    assert meta["npm"]["react"]["last_month"] == 1_000_000
    assert meta["pypi"]["torch"]["last_month"] == 5_000_000
    assert out["not_covered"] == ["SMCI"]             # no OSS surface mapped


def test_curated_maps_are_well_formed():
    for spec in digital_footprint.FOOTPRINTS.values():
        assert set(spec) <= {"github", "npm", "pypi", "docker"}
        assert any(spec.values())
    for spec in alt_data.ALT_SOURCES.values():
        assert set(spec) <= {"wiki", "itunes_app", "greenhouse"}
        assert spec.get("wiki")  # every entry has at least the wiki article
