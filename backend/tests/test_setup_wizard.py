"""Run setup logic offline; subprocess doubles stop package/network operations."""
import importlib.util
import os
from pathlib import Path
import subprocess
import shutil
import sys
from types import SimpleNamespace
import venv

import pytest


@pytest.fixture
def wizard(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "alphamaxxin_setup", Path(__file__).resolve().parents[2] / "setup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", str(tmp_path))
    monkeypatch.setattr(module, "REQUIREMENTS_PATH", str(tmp_path / "requirements.txt"))
    monkeypatch.setattr(module, "ENV_PATH", str(tmp_path / ".env"))
    monkeypatch.setattr(module, "PORTFOLIO_PATH", str(tmp_path / "Portfolio.md"))
    (tmp_path / "requirements.txt").write_text("requests\n")
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements-backend.txt").write_text("fastapi\n")
    monkeypatch.setattr(module, "ask_yes_no", lambda *args, **kwargs: False)
    return module


def test_setup_bootstraps_once_and_reexecutes_with_project_python(wizard, monkeypatch):
    commands = []
    python = os.path.join(wizard.HERE, ".venv", "Scripts" if os.name == "nt" else "bin",
                          "python.exe" if os.name == "nt" else "python")

    def run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["-m", "venv"]:
            Path(python).parent.mkdir(parents=True)
            Path(python).touch()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(wizard.subprocess, "run", run)
    ensure = getattr(wizard, "ensure_project_environment", lambda: None)
    with pytest.raises(SystemExit) as exit_info:
        ensure()
    assert exit_info.value.code == 0
    assert commands[0][1:] == ["-m", "venv", os.path.join(wizard.HERE, ".venv")]
    assert commands[1][0] == python
    assert commands[1][1] == os.path.join(wizard.HERE, "setup.py")


def test_project_interpreter_does_not_reenter_setup(wizard, monkeypatch):
    monkeypatch.setattr(wizard.sys, "prefix", os.path.join(wizard.HERE, ".venv"))
    monkeypatch.setattr(wizard.subprocess, "run", lambda *a, **k: pytest.fail("recursive setup"))
    ensure = getattr(wizard, "ensure_project_environment", lambda: None)
    ensure()


def test_bootstrap_reuses_existing_environment_and_propagates_failure(wizard, monkeypatch):
    python = Path(wizard.HERE, ".venv", "Scripts" if os.name == "nt" else "bin",
                  "python.exe" if os.name == "nt" else "python")
    python.parent.mkdir(parents=True)
    python.touch()
    commands = []
    monkeypatch.setattr(wizard.subprocess, "run", lambda command, **kwargs:
                        commands.append(command) or SimpleNamespace(returncode=7))
    with pytest.raises(SystemExit) as exit_info:
        wizard.ensure_project_environment()
    assert exit_info.value.code == 7
    assert len(commands) == 1
    assert commands[0][0] == str(python)


def test_native_launcher_uses_project_python_and_preserves_exit_code(tmp_path):
    # No pip or app/provider imports: this real interpreter runs a tiny fixture.
    project = tmp_path / "project with spaces"
    project.mkdir()
    venv.EnvBuilder(with_pip=False).create(project / ".venv")
    (project / "setup.py").write_text(
        'import sys\nprint("PROJECT_PREFIX=" + sys.prefix)\nraise SystemExit(7)\n')
    root = Path(__file__).resolve().parents[2]
    launcher = "start.bat" if os.name == "nt" else "start.sh"
    shutil.copyfile(root / launcher, project / launcher)
    command = ["cmd.exe", "/d", "/c", str(project / launcher)] if os.name == "nt" else [
        "bash", str(project / launcher)]
    result = subprocess.run(command, input="\n", capture_output=True, text=True,
                            cwd=project, timeout=20)
    assert result.returncode == 7, result.stdout + result.stderr
    assert "PROJECT_PREFIX=" + str(project / ".venv") in result.stdout


def test_dependency_failure_aborts_instead_of_continuing(wizard, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(wizard.subprocess, "run", run)
    monkeypatch.setattr(wizard, "ask_yes_no", lambda *a, **k: True)
    with pytest.raises((subprocess.CalledProcessError, SystemExit)):
        wizard.step_install_dependencies()
    assert len(calls) == 1


def test_broker_sdks_are_opt_in(wizard, monkeypatch):
    calls = []
    monkeypatch.setattr(wizard.subprocess, "run", lambda command, **kwargs:
                        calls.append(command) or SimpleNamespace(returncode=0))
    wizard.step_install_dependencies()
    assert all(not any(package in command for package in ("moomoo-api", "ib_async", "tigeropen"))
               for command in calls)


def test_only_selected_broker_sdk_is_installed(wizard, monkeypatch):
    calls = []
    monkeypatch.setattr(wizard.subprocess, "run", lambda command, **kwargs:
                        calls.append(command) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(wizard, "ask_yes_no", lambda question, **kwargs: "IBKR" in question)
    wizard.step_install_dependencies()
    assert calls[-1] == [sys.executable, "-m", "pip", "install", "ib_async"]
    assert all("moomoo-api" not in command and "tigeropen" not in command for command in calls)


@pytest.mark.parametrize("fail_step", ["ci", "build"])
def test_frontend_failure_aborts_and_uses_locked_install(wizard, monkeypatch, fail_step):
    Path(wizard.HERE, "frontend").mkdir()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if fail_step in command:
            if kwargs.get("check"):
                raise subprocess.CalledProcessError(1, command)
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(wizard.subprocess, "run", run)
    monkeypatch.setattr(wizard, "ask_yes_no", lambda *a, **k: True)
    with pytest.raises((subprocess.CalledProcessError, SystemExit)):
        wizard.step_frontend_build()
    assert any("ci" in command for command in calls)
    assert not any("install" in command for command in calls)
    if fail_step == "ci":
        assert not any("build" in command for command in calls)


def test_existing_dist_is_rebuilt_when_requested(wizard, monkeypatch):
    Path(wizard.HERE, "frontend", "dist").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(wizard.subprocess, "run", lambda command, **kwargs:
                        calls.append(command) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(wizard, "ask_yes_no", lambda *a, **k: True)
    wizard.step_frontend_build()
    assert any("ci" in command for command in calls)
    assert any("build" in command for command in calls)


def test_reconfigure_preserves_custom_gateway_once(wizard, monkeypatch):
    Path(wizard.ENV_PATH).write_text("MOOMOO_HOST=192.0.2.50\nMOOMOO_PORT=22222\n")
    monkeypatch.setattr(wizard, "ask_yes_no", lambda *a, **k: True)
    monkeypatch.setattr("builtins.input", lambda *a: "")
    wizard.step_configure_env()
    assert wizard._load_existing_env()["MOOMOO_HOST"] == "192.0.2.50"
    assert wizard._load_existing_env()["MOOMOO_PORT"] == "22222"
    assert Path(wizard.ENV_PATH).read_text().count("MOOMOO_HOST=") == 1
