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


def _index_path(reports_dir: str) -> str:
    return os.path.join(reports_dir, "index.json")


def _index_add(reports_dir: str, entry: dict) -> None:
    index = list_reports(reports_dir)
    index.insert(0, entry)
    with open(_index_path(reports_dir), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1)


def list_reports(reports_dir: str | None = None) -> list[dict]:
    reports_dir = reports_dir or REPORTS_DIR
    try:
        with open(_index_path(reports_dir), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def load_report(report_id: str, reports_dir: str | None = None) -> dict | None:
    reports_dir = reports_dir or REPORTS_DIR
    path = os.path.join(reports_dir, report_id, "report.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_report_html(report_id: str, reports_dir: str | None = None) -> str | None:
    reports_dir = reports_dir or REPORTS_DIR
    path = os.path.join(reports_dir, report_id, "report.html")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def delete_report(report_id: str, reports_dir: str | None = None) -> bool:
    reports_dir = reports_dir or REPORTS_DIR
    folder = os.path.join(reports_dir, report_id)
    if not os.path.isdir(folder):
        return False
    shutil.rmtree(folder)
    index = [e for e in list_reports(reports_dir) if e["id"] != report_id]
    with open(_index_path(reports_dir), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=1)
    return True
