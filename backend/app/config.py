"""Env loading + key-presence flags. Same manual .env parse as v1 runner.py
(no hard dependency on python-dotenv), pointed at the repo root."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"

LLM_KEYS = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
}
DATA_KEYS = {
    "finnhub": "FINNHUB_API_KEY",
    "alphavantage": "ALPHAVANTAGE_API_KEY",
    "fred": "FRED_API_KEY",
}


def load_env(env_file: Path | None = None) -> None:
    """Populate os.environ from .env without overwriting existing values."""
    env_file = env_file or ENV_FILE
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def key_status() -> dict:
    """Which keys are configured (presence only — values never leave the box)."""
    return {
        "llm": {name: bool(os.environ.get(var, "").strip())
                for name, var in LLM_KEYS.items()},
        "data": {name: bool(os.environ.get(var, "").strip())
                 for name, var in DATA_KEYS.items()},
    }
