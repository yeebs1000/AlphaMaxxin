"""Report persistence: reports/{YYYYMMDD_HHMMSS}_{preset}/report.{json,md,html}
plus a lightweight index for the history view. reports/ stays gitignored."""
import datetime
import json
import os
import re
import shutil
from pathlib import Path

from .render import render_report_html

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = str(REPO_ROOT / "reports")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "report"


def save_report(report: dict, reports_dir: str | None = None) -> str:
    """Persist a full report dict; returns the report id (folder name)."""
    reports_dir = reports_dir or REPORTS_DIR
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_id = f"{stamp}_{_slug(report['preset'])}"
    folder = os.path.join(reports_dir, report_id)
    os.makedirs(folder, exist_ok=True)
    report = {**report, "id": report_id}

    with open(os.path.join(folder, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False, default=str)

    markdown = report.get("sections", {}).get("synthesis", {}).get("markdown", "")
    with open(os.path.join(folder, "report.md"), "w", encoding="utf-8") as f:
        f.write(markdown)

    title = f"{report['preset']} — {report.get('target_label', 'Portfolio')}"
    with open(os.path.join(folder, "report.html"), "w", encoding="utf-8") as f:
        f.write(render_report_html(title, markdown))

    _index_add(reports_dir, {
        "id": report_id,
        "preset": report["preset"],
        "target_label": report.get("target_label", ""),
        "created_at": report.get("created_at", ""),
        "recommendations": len(report.get("sections", {})
                               .get("synthesis", {}).get("recommendations", [])),
        "cost_usd": report.get("costs", {}).get("usd", 0.0),
    })
    return report_id


def _confined_path(reports_dir: str, *parts: str) -> Path | None:
    try:
        root = Path(reports_dir).resolve()
        path = root.joinpath(*parts)
        if path == root or not path.is_relative_to(root) or path.resolve() != path:
            return None
        return path
    except (OSError, RuntimeError, ValueError):
        return None


def _report_path(report_id: str, reports_dir: str, filename: str | None = None) -> Path | None:
    if not isinstance(report_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", report_id):
        return None
    if re.fullmatch(r"con|prn|aux|nul|com[1-9]|lpt[1-9]", report_id, re.IGNORECASE):
        return None
    parts = (report_id, filename) if filename else (report_id,)
    return _confined_path(reports_dir, *parts)


def _index_path(reports_dir: str) -> Path | None:
    return _confined_path(reports_dir, "index.json")


def _index_add(reports_dir: str, entry: dict) -> None:
    path = _index_path(reports_dir)
    if path is None:
        raise ValueError("report index path must stay within the reports directory")
    index = list_reports(reports_dir)
    index.insert(0, entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1)


def list_reports(reports_dir: str | None = None) -> list[dict]:
    reports_dir = reports_dir or REPORTS_DIR
    path = _index_path(reports_dir)
    if path is None:
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def load_report(report_id: str, reports_dir: str | None = None) -> dict | None:
    reports_dir = reports_dir or REPORTS_DIR
    path = _report_path(report_id, reports_dir, "report.json")
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_report_html(report_id: str, reports_dir: str | None = None) -> str | None:
    reports_dir = reports_dir or REPORTS_DIR
    path = _report_path(report_id, reports_dir, "report.html")
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def delete_report(report_id: str, reports_dir: str | None = None) -> bool:
    reports_dir = reports_dir or REPORTS_DIR
    folder = _report_path(report_id, reports_dir)
    index_path = _index_path(reports_dir)
    if folder is None or index_path is None or not folder.is_dir():
        return False
    shutil.rmtree(folder)
    index = [e for e in list_reports(reports_dir) if e["id"] != report_id]
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1)
    return True
