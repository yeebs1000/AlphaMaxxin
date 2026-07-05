"""Watchlist store — plain JSON CRUD at data_store/watchlists.json
(gitignored). Shape: {"<id>": {"id", "name", "tickers": [...], "created_at"}}.
"""
import datetime
import json
import os
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WATCHLISTS_FILE = str(REPO_ROOT / "data_store" / "watchlists.json")


def _load(file_path=None) -> dict:
    file_path = file_path or WATCHLISTS_FILE
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict, file_path=None) -> None:
    file_path = file_path or WATCHLISTS_FILE
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def list_watchlists(file_path=None) -> list[dict]:
    return sorted(_load(file_path).values(), key=lambda w: w["created_at"])


def get_watchlist(watchlist_id: str, file_path=None) -> dict | None:
    return _load(file_path).get(watchlist_id)


def create_watchlist(name: str, tickers: list[str], file_path=None) -> dict:
    data = _load(file_path)
    wl = {
        "id": uuid.uuid4().hex[:12],
        "name": name.strip(),
        "tickers": _clean(tickers),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    data[wl["id"]] = wl
    _save(data, file_path)
    return wl


def update_watchlist(watchlist_id: str, name: str | None = None,
                     tickers: list[str] | None = None, file_path=None) -> dict | None:
    data = _load(file_path)
    wl = data.get(watchlist_id)
    if not wl:
        return None
    if name is not None:
        wl["name"] = name.strip()
    if tickers is not None:
        wl["tickers"] = _clean(tickers)
    _save(data, file_path)
    return wl


def delete_watchlist(watchlist_id: str, file_path=None) -> bool:
    data = _load(file_path)
    if watchlist_id not in data:
        return False
    del data[watchlist_id]
    _save(data, file_path)
    return True


def _clean(tickers: list[str]) -> list[str]:
    seen, out = set(), []
    for t in tickers:
        t = t.strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out
