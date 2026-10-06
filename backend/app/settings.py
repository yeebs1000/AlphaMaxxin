"""User settings — per-role model routing, persisted in data_store/
settings.json (gitignored). Never holds API keys; those stay in .env."""
import copy
import json
import os
from pathlib import Path

from .llm.router import DEFAULT_MODEL
from .llm.analysts import ANALYSTS

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = str(REPO_ROOT / "data_store" / "settings.json")

DEFAULT_SETTINGS = {
    "models": {role: DEFAULT_MODEL for role in [*ANALYSTS, "synthesis"]},
    "llm_cache_enabled": True,
    # Which markets broad scans (Opportunist etc.) cover — the dashboard
    # toggles write here. Region-scoped presets (Dragon Watch…) ignore this.
    "scan_markets": {"US": True, "SG": True, "HK": True, "JP": True, "KR": True},
}


def default_model() -> str:
    """Choose defaults from configured providers; existing saved IDs still win."""
    for key, model in (("GEMINI_API_KEY", DEFAULT_MODEL),
                       ("ANTHROPIC_API_KEY", "claude-sonnet-4-6"),
                       ("OPENAI_API_KEY", "gpt-4o-mini")):
        if os.environ.get(key, "").strip():
            return model
    if os.environ.get("LOCAL_LLM_BASE_URL", "").strip():
        model = os.environ.get("LOCAL_LLM_MODEL", "qwen3:14b").strip() or "qwen3:14b"
        return model if model.startswith(("local/", "ollama/")) else f"local/{model}"
    return DEFAULT_MODEL


def load_settings(file_path=None) -> dict:
    file_path = file_path or SETTINGS_FILE
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["models"] = {role: default_model() for role in [*ANALYSTS, "synthesis"]}
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
