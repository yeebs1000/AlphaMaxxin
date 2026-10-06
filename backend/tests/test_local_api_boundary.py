"""The localhost API rejects browser/Host requests before fake side effects."""
import asyncio

import httpx
import pytest

from app.api import reports as reports_api
from app.api.deps import get_registry
from app.main import create_app
from app.reports.progress import RunRegistry
from .fakes import make_registry


@pytest.fixture
def local_app(monkeypatch):
    effects = []

    async def fake_run(registry, body, emit, **kwargs):
        effects.append(("run", body["preset"]))
        return "fixture-report"

    def fake_delete(report_id):
        effects.append(("delete", report_id))
        return True

    def fake_save(settings):
        effects.append(("settings", settings))
        return settings

    monkeypatch.setattr(reports_api, "run_report", fake_run)
    monkeypatch.setattr(reports_api, "RUNS", RunRegistry())
    monkeypatch.setattr(reports_api.settings_mod, "load_settings", lambda: {
        "llm_cache_enabled": False})
    monkeypatch.setattr(reports_api.settings_mod, "save_settings", fake_save)
    monkeypatch.setattr(reports_api.store, "delete_report", fake_delete)
    app = create_app()
    registry = make_registry()
    app.dependency_overrides[get_registry] = lambda: registry
    return app, effects


async def _request(app, method, path, *, origin=None, host="127.0.0.1", content="",
                   content_type=None):
    headers = {"Origin": origin} if origin is not None else {}
    if content_type is not None:
        headers["Content-Type"] = content_type
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=f"http://{host}:8000") as client:
        response = await client.request(method, path, content=content, headers=headers)
    # Report runs are scheduled by the real route; let the immediate fake run
    # finish so the assertion observes whether the request triggered work.
    await asyncio.sleep(0)
    return response


@pytest.mark.parametrize("origin", ["http://evil.example", "null"])
@pytest.mark.parametrize("content_type", [None, "application/json"])
@pytest.mark.parametrize("method, path, content", [
    ("POST", "/api/reports/run", '{"preset": "Lite"}'),
    ("PUT", "/api/settings", '{"llm_cache_enabled": false}'),
    ("DELETE", "/api/reports/fixture-report", ""),
])
async def test_untrusted_browser_mutation_is_rejected_before_side_effect(
        local_app, origin, method, path, content, content_type):
    app, effects = local_app
    response = await _request(
        app, method, path, origin=origin, content=content, content_type=content_type)
    if content_type is None:
        assert "content-type" not in response.request.headers
    assert (response.status_code, effects) == (403, [])


@pytest.mark.parametrize("host", [
    "evil.example", "localhost.evil.example", "127.0.0.1.evil.example",
])
async def test_unsupported_host_cannot_start_report(local_app, host):
    app, effects = local_app
    response = await _request(
        app, "POST", "/api/reports/run", host=host, content='{"preset": "Lite"}',
        content_type="application/json")
    assert (response.status_code, effects) == (400, [])


async def test_unsupported_host_cannot_read_api_schema(local_app):
    app, effects = local_app
    response = await _request(app, "GET", "/openapi.json", host="evil.example")
    assert response.status_code == 400
    assert effects == []


@pytest.mark.parametrize("origin", [
    None, "http://localhost:8000", "http://127.0.0.1:8000",
    "http://localhost:5173", "http://127.0.0.1:5173",
])
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
async def test_local_browser_and_non_browser_clients_can_start_report(local_app, origin, host):
    app, effects = local_app
    response = await _request(
        app, "POST", "/api/reports/run", origin=origin, host=host,
        content='{"preset": "Lite"}', content_type="application/json")
    assert response.status_code == 200, response.text
    assert effects == [("run", "Lite")]


async def test_vite_preflight_keeps_allowed_cors_origin(local_app):
    app, effects = local_app
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000") as client:
        response = await client.options("/api/reports/run", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert effects == []
