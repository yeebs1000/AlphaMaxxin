"""Report reads and deletion stay within their offline temporary store."""
import os
import subprocess
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from app.api.reports import router
from app.reports import store


REPORT_ID = "20261006_120000_lite"
INVALID_IDS = [
    "", ".", "..", "../outside", "..\\outside", "nested/report",
    "nested\\report", "/absolute", "\\absolute", "C:\\absolute",
    "C:relative", " ", ".. ", "%2e%2e", "report\x00",
]


@pytest.fixture
def reports_dir(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    # Parent and current-directory artifacts expose traversal if validation
    # regresses, without reading or deleting anything outside pytest's temp dir.
    for folder in (tmp_path, reports, tmp_path / "outside"):
        folder.mkdir(exist_ok=True)
        (folder / "report.json").write_text('{"private": true}', encoding="utf-8")
        (folder / "report.html").write_text("private", encoding="utf-8")
    (reports / "index.json").write_text("[]", encoding="utf-8")
    return reports


@pytest.mark.parametrize("report_id", INVALID_IDS)
def test_invalid_id_cannot_read_json(report_id, reports_dir):
    assert store.load_report(report_id, str(reports_dir)) is None


@pytest.mark.parametrize("report_id", INVALID_IDS)
def test_invalid_id_cannot_read_html(report_id, reports_dir):
    assert store.load_report_html(report_id, str(reports_dir)) is None


@pytest.mark.parametrize("report_id", INVALID_IDS)
def test_invalid_id_cannot_delete(report_id, reports_dir, monkeypatch):
    remove = Mock()
    monkeypatch.setattr(store.shutil, "rmtree", remove)
    assert store.delete_report(report_id, str(reports_dir)) is False
    remove.assert_not_called()
    assert (reports_dir / "index.json").read_text(encoding="utf-8") == "[]"


def test_absolute_existing_report_cannot_be_read_or_deleted(reports_dir, tmp_path, monkeypatch):
    report_id = str(tmp_path / "outside")
    remove = Mock()
    monkeypatch.setattr(store.shutil, "rmtree", remove)
    assert store.load_report(report_id, str(reports_dir)) is None
    assert store.load_report_html(report_id, str(reports_dir)) is None
    assert store.delete_report(report_id, str(reports_dir)) is False
    remove.assert_not_called()


def test_generated_report_id_keeps_read_and_delete_behavior(tmp_path):
    reports = tmp_path / "reports"
    report_id = store.save_report(
        {"preset": "Dragon Watch", "target_label": "MSFT", "sections": {
            "synthesis": {"markdown": "# Saved report"}}}, str(reports))
    folder = reports / report_id
    assert folder.resolve().parent == reports.resolve()
    assert reports.resolve().is_relative_to(tmp_path.resolve())
    assert store.load_report(report_id, str(reports))["preset"] == "Dragon Watch"
    assert "Saved report" in store.load_report_html(report_id, str(reports))
    assert store.delete_report(report_id, str(reports)) is True
    assert not folder.exists()
    assert store.list_reports(str(reports)) == []


def test_existing_simple_report_id_remains_supported(reports_dir):
    report_id = "legacy-report_42"
    folder = reports_dir / report_id
    folder.mkdir()
    (folder / "report.json").write_text('{"preset": "Lite"}', encoding="utf-8")
    (folder / "report.html").write_text("saved report", encoding="utf-8")
    assert folder.resolve().parent == reports_dir.resolve()
    assert store.load_report(report_id, str(reports_dir)) == {"preset": "Lite"}
    assert store.load_report_html(report_id, str(reports_dir)) == "saved report"
    assert store.delete_report(report_id, str(reports_dir)) is True
    assert not folder.exists()


def _symlink(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        if os.name == "nt":
            pytest.skip(f"Windows symlink creation is unavailable: {exc}")
        raise


def test_report_directory_symlink_cannot_escape(reports_dir, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    _symlink(reports_dir / REPORT_ID, outside, directory=True)
    remove = Mock()
    monkeypatch.setattr(store.shutil, "rmtree", remove)
    assert store.load_report(REPORT_ID, str(reports_dir)) is None
    assert store.load_report_html(REPORT_ID, str(reports_dir)) is None
    assert store.delete_report(REPORT_ID, str(reports_dir)) is False
    remove.assert_not_called()
    assert (outside / "report.json").read_text(encoding="utf-8") == '{"private": true}'


@pytest.mark.skipif(os.name != "nt", reason="Junctions are a Windows filesystem feature")
def test_report_directory_junction_cannot_escape(reports_dir, tmp_path, monkeypatch):
    link = reports_dir / REPORT_ID
    outside = tmp_path / "outside"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True, text=True, check=False)
    if result.returncode:
        pytest.skip(f"Windows junction creation is unavailable: {result.stderr}")
    assert link.resolve() == outside.resolve()
    remove = Mock()
    monkeypatch.setattr(store.shutil, "rmtree", remove)
    assert store.load_report(REPORT_ID, str(reports_dir)) is None
    assert store.load_report_html(REPORT_ID, str(reports_dir)) is None
    assert store.delete_report(REPORT_ID, str(reports_dir)) is False
    remove.assert_not_called()


@pytest.mark.parametrize("filename, loader", [
    ("report.json", store.load_report),
    ("report.html", store.load_report_html),
])
def test_report_artifact_symlink_cannot_escape(filename, loader, reports_dir, tmp_path):
    folder = reports_dir / REPORT_ID
    folder.mkdir()
    _symlink(folder / filename, tmp_path / "outside" / filename)
    assert loader(REPORT_ID, str(reports_dir)) is None


def test_index_symlink_cannot_be_read_or_written_outside_store(reports_dir, tmp_path, monkeypatch):
    folder = reports_dir / REPORT_ID
    folder.mkdir()
    index = reports_dir / "index.json"
    index.unlink()
    outside_index = tmp_path / "outside" / "index.json"
    contents = f'[{{"id": "{REPORT_ID}"}}, {{"id": "private"}}]'
    outside_index.write_text(contents, encoding="utf-8")
    _symlink(index, outside_index)
    remove = Mock()
    monkeypatch.setattr(store.shutil, "rmtree", remove)
    assert store.list_reports(str(reports_dir)) == []
    assert store.delete_report(REPORT_ID, str(reports_dir)) is False
    remove.assert_not_called()
    assert folder.exists()
    assert outside_index.read_text(encoding="utf-8") == contents


@pytest.mark.parametrize("method, suffix", [("get", ""), ("get", "/html"), ("delete", "")])
async def test_encoded_parent_id_returns_missing(method, suffix, reports_dir, monkeypatch):
    monkeypatch.setattr(store, "REPORTS_DIR", str(reports_dir))
    remove = Mock()
    monkeypatch.setattr(store.shutil, "rmtree", remove)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, f"/api/reports/%2e%2e{suffix}")
    assert response.status_code == 404
    remove.assert_not_called()
