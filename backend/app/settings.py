"""User settings — per-role model routing, persisted in data_store/
settings.json (gitignored). Never holds API keys; those stay in .env."""
import json
import os
from pathlib import Path

from .llm.router import DEFAULT_MODEL

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = str(REPO_ROOT / "data_store" / "settings.json")

DEFAULT_SETTINGS = {
    "models": {
        "macro": DEFAULT_MODEL,
        "fundamentals": DEFAULT_MODEL,
        "technicals_options": DEFAULT_MODEL,
        "news_catalysts": DEFAULT_MODEL,
        "risk": DEFAULT_MODEL,
        "synthesis": "claude-sonnet-4-6",  # the one call worth the better tier
    },
    "llm_cache_enabled": True,
}


def load_settings(file_path=None) -> dict:
    file_path = file_path or SETTINGS_FILE
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            stored = json.load(f)
        settings["models"].update(stored.get("models", {}))
        for key in ("llm_cache_enabled",):
            if key in stored:
                settings[key] = stored[key]
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict, file_path=None) -> dict:
    file_path = file_path or SETTINGS_FILE
    merged = load_settings(file_path)
    merged["models"].update(settings.get("models", {}))
    for key in ("llm_cache_enabled",):
        if key in settings:
            merged[key] = settings[key]
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    return merged
