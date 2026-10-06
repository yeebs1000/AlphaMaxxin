"""Settings must cover every active role without changing saved model choices."""
import json

import pytest

from app import settings
from app.llm.analysts import ANALYSTS


@pytest.fixture(autouse=True)
def no_provider_credentials(monkeypatch):
    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                "LOCAL_LLM_BASE_URL", "LOCAL_LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("env,expected", [
    ({"GEMINI_API_KEY": "fixture"}, "gemini-3.5-flash-lite"),
    ({"ANTHROPIC_API_KEY": "fixture"}, "claude-sonnet-4-6"),
    ({"OPENAI_API_KEY": "fixture"}, "gpt-4o-mini"),
    ({"LOCAL_LLM_BASE_URL": "http://127.0.0.1:1234/v1",
      "LOCAL_LLM_MODEL": "fixture-model"}, "local/fixture-model"),
])
def test_new_roles_follow_configured_provider(monkeypatch, tmp_path, env, expected):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    got = settings.load_settings(str(tmp_path / "settings.json"))
    assert set(got["models"]) == set(ANALYSTS) | {"synthesis"}
    assert set(got["models"].values()) == {expected}


def test_saved_custom_ids_survive_provider_change_and_save(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture")
    path = str(tmp_path / "settings.json")
    with open(path, "w", encoding="utf-8") as file:
        json.dump({"models": {"macro": "local/my-custom:8b", "synthesis": "gpt-custom"}}, file)
    got = settings.load_settings(path)
    assert got["models"]["macro"] == "local/my-custom:8b"
    assert got["models"]["synthesis"] == "gpt-custom"
    assert got["models"].get("alternative_data") == "claude-sonnet-4-6"
    settings.save_settings({"models": {"digital_footprint": "local/another-model"}}, path)
    reloaded = settings.load_settings(path)
    assert reloaded["models"]["macro"] == "local/my-custom:8b"
    assert reloaded["models"]["digital_footprint"] == "local/another-model"


def test_all_roles_exist_without_provider_keys(tmp_path):
    got = settings.load_settings(str(tmp_path / "settings.json"))
    assert set(got["models"]) == set(ANALYSTS) | {"synthesis"}


def test_whitespace_key_does_not_choose_an_unconfigured_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "  ")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    assert settings.load_settings(str(tmp_path / "s.json"))["models"]["macro"] == "gpt-4o-mini"
