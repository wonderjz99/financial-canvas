"""Check the publication boundary without reading private research inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import re
from urllib.parse import urlsplit

PROFILE = "financial-visualizer-v2-public"
ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRECTORIES = {".git", ".local", "reports", "node_modules", "test-results", "playwright-report", "__pycache__", ".venv", "venv"}
BLOCKED_DIRECTORIES = {"data", ".local", "reports", ".checkpoints", "node_modules", "test-results", "playwright-report", "examples", "backups", ".venv", "venv", ".aws", ".ssh", "__pycache__"}
BLOCKED_FILES = {"财务动态图.html", "scripts/build_html.py", "scripts/probe_futu.py", "tests/browser/report.spec.cjs", "config/issuers.json"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
REVIEWED_REPORTS = {f"examples/reports/{symbol}.html": symbol for symbol in ("COST", "AAPL", "ADBE")}
EXAMPLE_FILES = set(REVIEWED_REPORTS) | {"examples/README.md", "examples/provenance.json"}


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
    if relative in EXAMPLE_FILES:
        return path
    if relative in BLOCKED_FILES or set(path.parts).intersection(BLOCKED_DIRECTORIES) or ".git" in path.parts:
        raise PublicationError("Excluded historical/runtime path: " + relative)
    if (path.name == ".env" or path.name.startswith(".env.") or path.suffix.lower() in SENSITIVE_SUFFIXES | {".pyc", ".pyo"}
            or path.name in {".npmrc", ".pypirc", ".netrc", "credentials", "id_rsa", "id_ed25519"}):
        raise PublicationError("Private configuration/key path: " + relative)
    # Reviewed examples return above; all other HTML except the empty shell is excluded.
    if path.suffix.lower() in {".html", ".htm"} and relative != "web/index.html":
        raise PublicationError("Generated or historical HTML cannot be published: " + relative)
    return path


def check_examples(paths, read_bytes):
    reports = set(paths).intersection(REVIEWED_REPORTS)
    if not reports:
        return 0
    if "examples/provenance.json" not in paths:
        raise PublicationError("Reviewed report examples require provenance")
    try:
        manifest = json.loads(read_bytes("examples/provenance.json"))
        records = manifest["reports"]
        if manifest.get("schemaVersion") != "1.0" or not isinstance(records, list):
            raise ValueError("Invalid example manifest")
        indexed = {r["path"]: r for r in records}
        if len(indexed) != len(records) or set(indexed) != reports:
            raise ValueError("Example files and provenance differ")
        for relative in reports:
            body = read_bytes(relative)
            record = indexed[relative]
            if hashlib.sha256(body).hexdigest() != record["sha256"]:
                raise ValueError("Example hash differs: " + relative)
            html = body.decode("utf-8")
            match = re.search(r"window\.__FV_REPORTS__=(.*?);window\.__FV_REPORT__=", html, re.S)
            if not match or "window.__FV_OFFLINE__=true" not in html:
                raise ValueError("Example is not a generated offline report")
            registry = json.loads(match.group(1))
            symbol = REVIEWED_REPORTS[relative]
            if set(registry) != {symbol} or record["symbol"] != symbol:
                raise ValueError("Example must contain only its reviewed company")
            report = registry[symbol]
            if report.get("symbol") != symbol or report.get("schemaVersion") != "1.0":
                raise ValueError("Example report identity differs")
            if (report["years"] != record["years"] or report["company"]["currency"] != record["currency"]
                    or report["snapshot"]["asOf"] != record["asOf"]):
                raise ValueError("Example period/currency/cutoff provenance differs")
            facts = report["facts"]
            if not isinstance(facts, dict) or not facts:
                raise ValueError("Example facts are missing")
            sources = {fact.get("source") for fact in facts.values()}
            if not sources <= {"SEC", "IR_manual", "calculated"} or sorted(sources) != record["factSources"]:
                raise ValueError("Example contains an unreviewed or vendor fact source")
            for fact in facts.values():
                if fact["source"] != "calculated":
                    url = urlsplit(fact.get("sourceUrl") or "")
                    if url.scheme != "https" or url.hostname not in {"www.sec.gov", "sec.gov", "data.sec.gov"}:
                        raise ValueError("Reviewed examples must retain official SEC source links")
            if re.search(r'<(?:script|iframe)\b[^>]*\bsrc\s*=', html, re.I):
                raise ValueError("Example loads an external runtime")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PublicationError("Invalid reviewed example provenance: " + str(exc)) from exc
    return len(reports)


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
                if path.name != "__pycache__" and not (path.parent == root and path.name in RUNTIME_DIRECTORIES):
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
    example_count = check_examples(paths, lambda name: (root / name).read_bytes())
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
        revisions = subprocess.check_output(["git", "rev-list", "--all", "--full-history", "--", "examples"], cwd=root).decode().splitlines()
        for revision in revisions:
            names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "-z", revision, "--", "examples"], cwd=root).decode().split("\0")
            check_examples({n for n in names if n}, lambda name, ref=revision: subprocess.check_output(["git", "show", ref + ":" + name], cwd=root))
    return {"profile": PROFILE, "license": "MIT", "filesChecked": len(paths), "historyPathsChecked": len(history_paths), "reviewedReports": example_count, "mode": "git-index" if tracked else "working-tree"}


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
