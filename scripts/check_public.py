"""Check the publication boundary without reading private research inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

PROFILE = "financial-visualizer-v2-public"
ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRECTORIES = {".git", ".local", "reports", "node_modules", "test-results", "playwright-report", "__pycache__", ".venv", "venv"}
BLOCKED_DIRECTORIES = {"data", ".local", "reports", ".checkpoints", "node_modules", "test-results", "playwright-report", "examples", "backups", ".venv", "venv", ".aws", ".ssh", "__pycache__"}
BLOCKED_FILES = {"财务动态图.html", "scripts/build_html.py", "scripts/probe_futu.py", "tests/browser/report.spec.cjs", "config/issuers.json"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


class PublicationError(ValueError):
    """A candidate violates the explicit public distribution boundary."""


def validate_relative(value):
    if not isinstance(value, str) or not value or "\\" in value or any(ord(c) < 32 for c in value):
        raise PublicationError("Invalid publication path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")) or ":" in path.parts[0]:
        raise PublicationError("Publication paths must be normalized relative paths")
    return path


def permitted_file(relative):
    path = validate_relative(relative)
    if relative in BLOCKED_FILES or set(path.parts).intersection(BLOCKED_DIRECTORIES) or ".git" in path.parts:
        raise PublicationError("Excluded historical/runtime path: " + relative)
    if (path.name == ".env" or path.name.startswith(".env.") or path.suffix.lower() in SENSITIVE_SUFFIXES | {".pyc", ".pyo"}
            or path.name in {".npmrc", ".pypirc", ".netrc", "credentials", "id_rsa", "id_ed25519"}):
        raise PublicationError("Private configuration/key path: " + relative)
    # The only shipped HTML is the empty application shell; no generated reports or prototypes.
    if path.suffix.lower() in {".html", ".htm"} and relative != "web/index.html":
        raise PublicationError("Generated or historical HTML cannot be published: " + relative)
    return path


def public_profile(root):
    marker = Path(root) / "PUBLIC_RELEASE.json"
    if not marker.is_file():
        return False
    try:
        return json.loads(marker.read_text(encoding="utf-8")).get("profile") == PROFILE
    except (OSError, ValueError, AttributeError):
        return False


def candidate_paths(root, tracked=False):
    root = Path(root).resolve()
    if tracked:
        try:
            top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
            if Path(top).resolve() != root:
                raise PublicationError("Tracked-file checks require this candidate's own Git repository")
            raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise PublicationError("Cannot inspect candidate Git index") from exc
        return [p for p in raw.decode("utf-8").split("\0") if p]
    result = []
    def visit(directory):
        for path in directory.iterdir():
            if path.is_symlink():
                raise PublicationError("Symlinks are not part of the public export: " + path.relative_to(root).as_posix())
            if path.name == ".git":
                continue
            if path.is_dir():
                if path.name not in RUNTIME_DIRECTORIES:
                    visit(path)
            elif path.is_file():
                result.append(path.relative_to(root).as_posix())
    visit(root)
    return sorted(result)


def check_candidate(root, tracked=False, history=False):
    root = Path(root).resolve()
    if not public_profile(root):
        raise PublicationError("Missing or invalid V2 public profile")
    marker = json.loads((root / "PUBLIC_RELEASE.json").read_text(encoding="utf-8"))
    if marker.get("schemaVersion") != "1.0" or marker.get("license") != "MIT" or marker.get("includesResearchHistory") is not False:
        raise PublicationError("Public profile identity, license or history declaration is invalid")
    required = {"LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "scripts/report.py", "scripts/verify.py", "tests/test_report_v2.py", "tests/browser/v2.spec.cjs"}
    paths = candidate_paths(root, tracked)
    if not required <= set(paths):
        raise PublicationError("Required public distribution files are missing")
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    if not license_text.startswith("MIT License\n") or "Copyright (c) 2026 wonderjz99" not in license_text:
        raise PublicationError("The chosen MIT notice is missing")
    for relative in paths:
        permitted_file(relative)
        path = root / relative
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise PublicationError("Candidate files must remain inside its own root")
    history_paths = set()
    if history:
        # Inspect historical paths as well as the current tree; never display commit identities or blob contents.
        candidate_paths(root, tracked=True)
        try:
            raw = subprocess.check_output(["git", "log", "--all", "--format=", "--name-only", "-z"], cwd=root, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as exc:
            raise PublicationError("Cannot inspect candidate Git history") from exc
        history_paths = {p.strip("\n") for p in raw.decode("utf-8").split("\0") if p.strip("\n")}
        for relative in history_paths:
            permitted_file(relative)
    return {"profile": PROFILE, "license": "MIT", "filesChecked": len(paths), "historyPathsChecked": len(history_paths), "mode": "git-index" if tracked else "working-tree"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--tracked", action="store_true", help="Also reject excluded files forced into this repository's Git index")
    parser.add_argument("--history", action="store_true", help="Reject excluded paths present in any fetched commit history")
    args = parser.parse_args(argv)
    try:
        result = check_candidate(args.root, args.tracked, args.history)
    except (PublicationError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
