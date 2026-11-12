"""Versioned, integrity-checked public SEC acquisition for V2 only."""
from __future__ import annotations

import hashlib
import json
import re
import time
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .providers import ReportError


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, ValueError) as exc:
        raise ReportError("input_invalid", f"Unreadable or invalid JSON: {Path(path).name}") from exc


def write_json(path, value):
    write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def write_bytes(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".json-", suffix=".tmp", delete=False) as handle:
        temp = Path(handle.name)
        handle.write(body)
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


class SecCache:
    """Never replace a successful response with an error or corrupt response."""

    def __init__(self, root, user_agent, offline=False, refresh=False):
        self.root = Path(root)
        self.user_agent = user_agent
        self.offline = offline
        self.refresh = refresh
        self.warnings = []
        self.last_request = 0.0

    def _saved(self, directory, url, validator):
        pointer = directory / "latest.json"
        if not pointer.exists():
            return None
        record = read_json(pointer)
        version = record.get("version", "")
        if not re.fullmatch(r"[a-f0-9]{64}", version):
            raise ReportError("cache_invalid", "Invalid SEC cache version identifier.")
        meta = read_json(directory / (version + ".meta.json"))
        body = (directory / (version + ".body")).read_bytes()
        if sha(body) != version or meta.get("sha256") != version or meta.get("url") != url:
            raise ReportError("cache_invalid", "SEC cache integrity or URL mismatch.")
        validator(body)
        return body, {**meta, "mode": "cache"}

    def get(self, url, validator):
        directory = self.root / sha(url.encode())
        saved = None
        try:
            saved = self._saved(directory, url, validator)
        except (ReportError, OSError, ValueError, KeyError, TypeError) as exc:
            self.warnings.append({"code": "cache_invalid", "url": url, "detail": str(exc)})
            if self.offline:
                raise ReportError("cache_invalid", "The offline SEC cache is corrupt; refresh it online.") from exc
        if saved and not self.refresh:
            return saved
        if self.offline:
            raise ReportError("cache_missing", "No verified offline cache is available for " + url)
        try:
            time.sleep(max(0, 0.15 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json,text/html"})
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(32_000_001)
                if response.status != 200 or len(body) > 32_000_000:
                    raise ValueError("Invalid SEC response status or size")
                validator(body)
                version = sha(body)
                meta = {"url": url, "sha256": version, "version": version, "retrievedAt": now(),
                        "responseDate": response.headers.get("Date"), "contentType": response.headers.get("Content-Type"),
                        "bytes": len(body), "status": 200}
            directory.mkdir(parents=True, exist_ok=True)
            # Keep a verified first acquisition timestamp; repair corrupt metadata after a successful fetch.
            try:
                previous = read_json(directory / (version + ".meta.json"))
                if previous.get("url") == url and previous.get("sha256") == version and previous.get("retrievedAt"):
                    meta = previous
            except ReportError:
                pass
            write_bytes(directory / (version + ".body"), body)
            write_json(directory / (version + ".meta.json"), meta)
            write_json(directory / "latest.json", {"version": version})
            return body, {**meta, "mode": "network"}
        except (OSError, ValueError, ReportError) as exc:
            if saved:
                self.warnings.append({"code": "refresh_failed_using_cache", "url": url,
                                      "version": saved[1]["version"], "retrievedAt": saved[1]["retrievedAt"], "detail": str(exc)})
                return saved[0], {**saved[1], "mode": "stale_cache"}
            raise ReportError("fetch_failed", "SEC acquisition failed with no verified cache: " + url) from exc


def json_validator(required):
    def validate(body):
        data = json.loads(body)
        if not isinstance(data, dict) or not set(required) <= set(data):
            raise ValueError("Unexpected SEC JSON schema")
    return validate


def html_validator(body):
    text = body.decode("utf-8", errors="replace").lower()
    if "<html" not in text or not ("<ix:" in text or "<table" in text) or "undeclared automated tool" in text:
        raise ValueError("SEC did not return a readable filing HTML")
