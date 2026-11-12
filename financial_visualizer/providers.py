"""Immutable SEC snapshots and explicit, offline supplemental data sources."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import probe_sec
from .issuers import get_issuer, supported_symbols

ROOT = Path(__file__).resolve().parents[1]
SEED_ROOT = ROOT / "data" / "probes" / "2026-11-09"
DEFAULT_CACHE = ROOT / ".local" / "cache"


class ReportError(Exception):
    """An expected report or provider error safe to expose as a diagnostic code."""

    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def normalize_symbol(value, registry=None):
    if not isinstance(value, str):
        raise ReportError("unsupported_symbol", "A supported stock symbol is required.")
    symbol = value.strip().upper()
    if symbol.startswith("US."):
        symbol = symbol[3:]
    if symbol not in supported_symbols(registry):
        raise ReportError("unsupported_symbol", "The stock symbol is not present in the selected issuer registry.", 404)
    return symbol


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReportError("snapshot_invalid", "The saved snapshot could not be read.", 500) from exc


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fetch_endpoint(url, user_agent):
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=25) as response:
        body = response.read(16_000_001)
        if len(body) > 16_000_000:
            raise ReportError("response_too_large", "SEC response exceeded the snapshot size limit.", 502)
        if response.status != 200:
            raise ReportError("refresh_failed", f"SEC returned HTTP {response.status}.", 502)
        return body, {"status": response.status, "content_type": response.headers.get("Content-Type"),
                      "response_date": response.headers.get("Date")}


def _analyze(symbol, directory, as_of, registry=None):
    try:
        issuer = probe_sec.analyze_issuer(symbol, directory, as_of, registry=registry)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise ReportError("snapshot_invalid", "SEC snapshot did not satisfy the financial source contract.", 502) from exc
    if issuer.get("status") != "analyzed" or len(issuer.get("periods", [])) < 1:
        raise ReportError("snapshot_invalid", "SEC snapshot identity, integrity or annual periods could not be verified.", 502)
    return issuer


def _load_saved(symbol, cache_root, registry=None):
    location = cache_root / symbol
    pointer_path = location / "latest.json"
    if not pointer_path.exists():
        return None
    pointer = _read_json(pointer_path)
    snapshot_id = pointer.get("id", "")
    if not isinstance(snapshot_id, str) or not snapshot_id or Path(snapshot_id).name != snapshot_id or snapshot_id.startswith("."):
        raise ReportError("snapshot_invalid", "Saved snapshot identifier is invalid.", 500)
    directory = location / snapshot_id
    manifest = _read_json(directory / "snapshot.json")
    if manifest.get("symbol") != symbol or manifest.get("id") != snapshot_id:
        raise ReportError("snapshot_invalid", "Snapshot identity does not match its manifest.", 500)
    issuer = _analyze(symbol, directory, manifest["asOf"], registry)
    return issuer, {**manifest, "mode": "cache"}


def load_snapshot(symbol, cache_root=None, refresh=False, registry=None):
    """Read verified saved facts; only an explicit refresh may use the network."""
    symbol = normalize_symbol(symbol, registry)
    cache_root = Path(cache_root) if cache_root is not None else DEFAULT_CACHE
    if refresh:
        return refresh_snapshot(symbol, cache_root, registry=registry)
    saved = _load_saved(symbol, cache_root, registry)
    if saved is not None:
        return saved
    directory = SEED_ROOT / "sec"
    if not (directory / f"{symbol}-companyfacts.json").exists():
        raise ReportError("snapshot_missing", "No saved financial snapshot exists for the registered issuer; refresh must be explicitly requested.", 404)
    issuer = _analyze(symbol, directory, "2026-11-09", registry)
    metadata = issuer["acquisition"]
    identity = hashlib.sha256("|".join(metadata[k]["sha256"] for k in ("submissions", "companyfacts")).encode()).hexdigest()[:24]
    return issuer, {"id": f"seed-{symbol}-{identity}", "symbol": symbol, "asOf": "2026-11-09",
                    "retrievedAt": max(metadata[k]["retrieved_at"] for k in metadata), "source": "SEC", "mode": "bundled"}


def refresh_snapshot(symbol, cache_root=None, user_agent=None, registry=None):
    """Fetch two endpoints into a new snapshot; publish its pointer only after validation."""
    symbol = normalize_symbol(symbol, registry)
    cache_root = Path(cache_root) if cache_root is not None else DEFAULT_CACHE
    location = cache_root / symbol
    location.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    as_of = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    user_agent = user_agent or "FinancialVisualizer/1.0 (local public-filing research)"
    stage = Path(tempfile.mkdtemp(prefix=".pending-", dir=location))
    try:
        cik = get_issuer(symbol, registry)["cik"]
        for index, (kind, endpoint) in enumerate((
            ("submissions", f"https://data.sec.gov/submissions/CIK{cik}.json"),
            ("companyfacts", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"),
        )):
            if index:
                time.sleep(1.1)
            body, response_meta = _fetch_endpoint(endpoint, user_agent)
            # Parse before persistence; amounts are parsed as Decimal by the analyzer.
            json.loads(body)
            path = stage / f"{symbol}-{kind}.json"
            path.write_bytes(body)
            _write_json(stage / f"{symbol}-{kind}.meta.json", {
                "url": endpoint, "as_of": as_of, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "transport": "urllib", "user_agent": user_agent, "bytes": len(body), "sha256": _sha(path), **response_meta,
            })
        issuer = _analyze(symbol, stage, as_of, registry)
        digest = hashlib.sha256("|".join(issuer["acquisition"][k]["sha256"] for k in ("submissions", "companyfacts")).encode()).hexdigest()[:12]
        snapshot_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + digest
        manifest = {"id": snapshot_id, "symbol": symbol, "asOf": as_of,
                    "retrievedAt": datetime.now(timezone.utc).isoformat(), "source": "SEC"}
        _write_json(stage / "snapshot.json", manifest)
        final = location / snapshot_id
        stage.rename(final)
        pointer_tmp = location / f".latest-{snapshot_id}.tmp"
        _write_json(pointer_tmp, {"id": snapshot_id})
        pointer_tmp.replace(location / "latest.json")
        return issuer, {**manifest, "mode": "refreshed"}
    except ReportError:
        raise
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        raise ReportError("refresh_failed", "SEC refresh failed; the previous snapshot was preserved.", 502) from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage)
