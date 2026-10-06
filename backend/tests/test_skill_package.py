"""The standalone bundle contains portable skills, never repository state."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = REPO_ROOT / "scripts" / "build_skills_release.py"
SKILL_NAMES = (
    "alpha-alternative-data", "alpha-catalysts-capital", "alpha-fundamentals",
    "alpha-macro", "alpha-portfolio-risk", "alpha-quant-validation",
    "alpha-rates-fx-commodities", "alpha-research", "alpha-signal-synthesis",
    "alpha-technicals-liquidity",
)


def builder():
    assert BUILDER_PATH.is_file(), "The standalone release builder is missing"
    spec = importlib.util.spec_from_file_location("skills_release", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True)


@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "source"
    root = repo / ".agents" / "skills"
    root.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "core.autocrlf", "false")
    (repo / "LICENSE").write_bytes((REPO_ROOT / "LICENSE").read_bytes())
    (root / "LICENSE").write_bytes((repo / "LICENSE").read_bytes())
    (root / "README.md").write_text("# Standalone research skills\n", encoding="utf-8")
    (repo / "INSTALL_SKILLS.md").write_text("# Install the skills\n", encoding="utf-8")
    plugin = root / ".claude-plugin"
    plugin.mkdir()
    (plugin / "plugin.json").write_text(json.dumps({
        "name": "alphamaxx-research", "version": "0.1.0",
        "author": {"name": "Yeebs"}, "license": "MIT", "skills": ["./"],
    }) + "\n", encoding="utf-8")
    for name in SKILL_NAMES:
        skill = root / name
        (skill / "agents").mkdir(parents=True)
        (skill / "LICENSE").write_bytes((repo / "LICENSE").read_bytes())
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Research this topic.\n---\n"
            "Use source-backed evidence.\n", encoding="utf-8")
        (skill / "agents" / "openai.yaml").write_text(
            "interface:\n  display_name: Research\n", encoding="utf-8")
    (root / "alpha-macro" / "references").mkdir()
    (root / "alpha-macro" / "references" / "regions.md").write_text(
        "# Regions\nUnited States\n", encoding="utf-8")
    scripts = root / "alpha-signal-synthesis" / "scripts"
    scripts.mkdir()
    (scripts / "aggregate_signals.py").write_bytes(
        (REPO_ROOT / ".agents" / "skills" / "alpha-signal-synthesis"
         / "scripts" / "aggregate_signals.py").read_bytes())
    # Even mistakenly tracked artifacts and credentials must stay out.
    junk = root / "alpha-macro" / "__pycache__"
    junk.mkdir()
    (junk / "secret.pyc").write_bytes(b"private cache bytes")
    (root / "alpha-macro" / ".env").write_text("API_KEY=private\n", encoding="utf-8")
    (root / "alpha-macro" / "private.md").write_text("personal holdings\n", encoding="utf-8")
    (repo / "backend").mkdir()
    (repo / "backend" / "private.py").write_text("private app state\n", encoding="utf-8")
    git(repo, "add", ".")
    (root / "alpha-macro" / "references" / "untracked.md").write_text(
        "private untracked draft\n", encoding="utf-8")
    return repo


def test_bundle_contains_only_tracked_portable_skills(source_repo, tmp_path):
    archive, checksum = builder().build_release(source_repo, tmp_path / "release")
    with zipfile.ZipFile(archive) as package:
        expected = {f"{name}/SKILL.md" for name in SKILL_NAMES}
        expected |= {f"{name}/agents/openai.yaml" for name in SKILL_NAMES}
        expected |= {f"{name}/LICENSE" for name in SKILL_NAMES}
        expected |= {"README.md", "LICENSE", "INSTALL_SKILLS.md",
                     ".claude-plugin/plugin.json", "alpha-macro/references/regions.md",
                     "alpha-signal-synthesis/scripts/aggregate_signals.py"}
        assert set(package.namelist()) == expected
        assert package.read("LICENSE").decode("utf-8").startswith("MIT License\n")
        assert "Copyright (c) 2026 yeebs1000" in package.read("LICENSE").decode("utf-8")
        for name in SKILL_NAMES:
            assert package.read(f"{name}/LICENSE") == package.read("LICENSE")
        manifest = json.loads(package.read(".claude-plugin/plugin.json"))
        assert manifest["skills"] == ["./"]
    assert checksum.read_text(encoding="utf-8") == (
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  alphamaxx-skills.zip\n")


def test_bundle_is_stable_across_line_endings_and_file_times(source_repo, tmp_path):
    first, _ = builder().build_release(source_repo, tmp_path / "first")
    for name in git(source_repo, "ls-files").stdout.splitlines():
        path = source_repo / name
        if path.suffix != ".pyc":
            content = path.read_bytes().replace(b"\r\n", b"\n")
            path.write_bytes(content.replace(b"\n", b"\r\n"))
    second, _ = builder().build_release(source_repo, tmp_path / "second")
    assert first.read_bytes() == second.read_bytes()


def test_bundle_uses_current_tracked_edits(source_repo, tmp_path):
    skill = source_repo / ".agents" / "skills" / "alpha-macro" / "SKILL.md"
    skill.write_text("Revised current working copy\n", encoding="utf-8")
    archive, _ = builder().build_release(source_repo, tmp_path / "release")
    with zipfile.ZipFile(archive) as package:
        assert package.read("alpha-macro/SKILL.md") == b"Revised current working copy\n"


def test_extracted_calculator_runs_without_the_application(source_repo, tmp_path):
    archive, _ = builder().build_release(source_repo, tmp_path / "release")
    extracted = tmp_path / "installed"
    with zipfile.ZipFile(archive) as package:
        package.extractall(extracted)
    example = tmp_path / "scores.json"
    example.write_text(json.dumps({
        "asset": "SPY", "horizon": "positional", "inputs": [
            {"name": "macro", "asset": "SPY", "horizon": "positional",
             "weight": 1, "score": 2, "confidence": "High", "direction_mapped": True},
            {"name": "fundamentals", "asset": "SPY", "horizon": "positional",
             "weight": 1, "score": None},
        ],
    }), encoding="utf-8")
    result = subprocess.run([
        sys.executable, str(extracted / "alpha-signal-synthesis" / "scripts"
                            / "aggregate_signals.py"), str(example),
    ], cwd=tmp_path, check=True, capture_output=True, text=True)
    score = json.loads(result.stdout)
    assert score["final_score"] == 2
    assert score["coverage"] == 0.5
    assert score["excluded"] == [{"name": "fundamentals", "reason": "unavailable", "weight": 1.0}]


def test_missing_skill_fails_before_writing_a_release(source_repo, tmp_path):
    (source_repo / ".agents" / "skills" / "alpha-macro" / "SKILL.md").unlink()
    output = tmp_path / "release"
    with pytest.raises(ValueError, match="alpha-macro/SKILL.md"):
        builder().build_release(source_repo, output)
    assert not (output / "alphamaxx-skills.zip").exists()


@pytest.mark.parametrize("omission", ["untracked", "missing"])
def test_install_document_omission_fails_before_writing_a_release(source_repo, tmp_path, omission):
    if omission == "untracked":
        git(source_repo, "rm", "--cached", "INSTALL_SKILLS.md")
    else:
        (source_repo / "INSTALL_SKILLS.md").unlink()
    output = tmp_path / "release"
    with pytest.raises(ValueError, match="INSTALL_SKILLS.md"):
        builder().build_release(source_repo, output)
    assert not output.exists()


@pytest.mark.parametrize("license_path", ["LICENSE", "alpha-macro/LICENSE"])
def test_license_drift_rejects_the_bundle(source_repo, tmp_path, license_path):
    (source_repo / ".agents" / "skills" / license_path).write_text(
        "Wrong attribution\n", encoding="utf-8")
    with pytest.raises(ValueError, match="LICENSE"):
        builder().build_release(source_repo, tmp_path / "release")


@pytest.mark.parametrize("omission", ["untracked", "missing"])
def test_individual_skill_license_is_required_before_writing_a_release(source_repo, tmp_path, omission):
    license_path = ".agents/skills/alpha-macro/LICENSE"
    if omission == "untracked":
        git(source_repo, "rm", "--cached", license_path)
    else:
        (source_repo / license_path).unlink()
    output = tmp_path / "release"
    with pytest.raises(ValueError, match="alpha-macro/LICENSE"):
        builder().build_release(source_repo, output)
    assert not output.exists()


def test_builder_cli_supports_a_different_working_directory(source_repo, tmp_path):
    assert BUILDER_PATH.is_file(), "The standalone release builder is missing"
    output = tmp_path / "release"
    result = subprocess.run([
        sys.executable, str(BUILDER_PATH), "--repo-root", str(source_repo),
        "--output-dir", str(output),
    ], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (output / "alphamaxx-skills.zip").is_file()
    assert (output / "SHA256SUMS").is_file()
