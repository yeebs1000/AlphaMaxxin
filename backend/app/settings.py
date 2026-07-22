"""User settings — per-role model routing, persisted in data_store/
settings.json (gitignored). Never holds API keys; those stay in .env."""
import copy
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
        "order_book": DEFAULT_MODEL,
        # Everything defaults to the cheap flash-lite tier; bump any role
        # (synthesis especially) to gemini-3.6-flash in Settings when wanted.
        "synthesis": DEFAULT_MODEL,
    },
    "llm_cache_enabled": True,
    # Which markets broad scans (Opportunist etc.) cover — the dashboard
    # toggles write here. Region-scoped presets (Dragon Watch…) ignore this.
    "scan_markets": {"US": True, "SG": True, "HK": True, "JP": True, "KR": True},
}


def load_settings(file_path=None) -> dict:
    file_path = file_path or SETTINGS_FILE
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            stored = json.load(f)
        settings["models"].update(stored.get("models", {}))
        settings["scan_markets"].update(stored.get("scan_markets", {}))
        if "llm_cache_enabled" in stored:
            settings["llm_cache_enabled"] = stored["llm_cache_enabled"]
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict, file_path=None) -> dict:
    file_path = file_path or SETTINGS_FILE
    merged = load_settings(file_path)
    merged["models"].update(settings.get("models", {}))
    merged["scan_markets"].update(settings.get("scan_markets", {}))
    if "llm_cache_enabled" in settings:
        merged["llm_cache_enabled"] = settings["llm_cache_enabled"]
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
    return merged
