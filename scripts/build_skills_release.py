"""Build the skills-only ZIP and its checksum from tracked, portable source files."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile


SKILL_NAMES = {
    "alpha-alternative-data", "alpha-catalysts-capital", "alpha-fundamentals",
    "alpha-macro", "alpha-portfolio-risk", "alpha-quant-validation",
    "alpha-rates-fx-commodities", "alpha-research", "alpha-signal-synthesis",
    "alpha-technicals-liquidity",
}
SKILLS_ROOT = PurePosixPath(".agents/skills")
ROOT_FILES = {"README.md", "LICENSE", ".claude-plugin/plugin.json"}


def package_name(tracked_path):
    """Accept the documented skill layout, rather than arbitrary tracked files."""
    path = PurePosixPath(tracked_path)
    if path == PurePosixPath("INSTALL_SKILLS.md"):
        return "INSTALL_SKILLS.md"
    if not path.is_relative_to(SKILLS_ROOT):
        return None
    relative = path.relative_to(SKILLS_ROOT)
    if relative.as_posix() in ROOT_FILES:
        return relative.as_posix()
    parts = relative.parts
    if len(parts) < 2 or parts[0] not in SKILL_NAMES:
        return None
    rest = PurePosixPath(*parts[1:])
    if rest.as_posix() in {"SKILL.md", "LICENSE", "agents/openai.yaml"}:
        return relative.as_posix()
    if (len(parts) >= 3 and parts[1] in {"references", "scripts"}
            and all(not part.startswith(".") and part != "__pycache__" for part in parts)
            and relative.suffix == {"references": ".md", "scripts": ".py"}[parts[1]]):
        return relative.as_posix()
    return None


def build_release(repo_root, output_dir):
    repo_root = Path(repo_root).resolve()
    tracked = subprocess.check_output([
        "git", "-C", str(repo_root), "ls-files", "-z", "--",
        SKILLS_ROOT.as_posix(), "INSTALL_SKILLS.md",
    ]).decode("utf-8").split("\0")
    contents = {}
    for tracked_path in tracked:
        name = package_name(tracked_path)
        if name is None:
            continue
        source = repo_root / tracked_path
        if not source.is_file():
            raise ValueError(f"Required tracked file is missing: {name}")
        if source.resolve() != source:
            raise ValueError(f"Linked source files are unsupported: {name}")
        contents[name] = source.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").encode("utf-8")
    required = ROOT_FILES | {"INSTALL_SKILLS.md"} | {
        f"{name}/{filename}" for name in SKILL_NAMES for filename in {"SKILL.md", "LICENSE"}
    }
    missing = required - contents.keys()
    if missing:
        raise ValueError(f"Required tracked files are missing: {', '.join(sorted(missing))}")
    root_license = (repo_root / "LICENSE").read_bytes()
    for license_path in ["LICENSE", *(f"{name}/LICENSE" for name in sorted(SKILL_NAMES))]:
        if (repo_root / SKILLS_ROOT / license_path).read_bytes() != root_license:
            raise ValueError(f"The skills {license_path} must be byte-identical to the root LICENSE")
    manifest = json.loads(contents[".claude-plugin/plugin.json"])
    if manifest.get("name") != "alphamaxx-research" or manifest.get("skills") != ["./"]:
        raise ValueError("The Claude manifest must load the skills from the plugin root")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / "alphamaxx-skills.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name, data in sorted(contents.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(entry, data, compresslevel=9)
    checksum = output_dir / "SHA256SUMS"
    checksum.write_bytes(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n".encode("ascii"))
    return archive, checksum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Directory for alphamaxx-skills.zip and SHA256SUMS")
    args = parser.parse_args()
    try:
        archive, checksum = build_release(args.repo_root, args.output_dir)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Cannot build skills release: {exc}", file=sys.stderr)
        return 1
    print(archive)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
