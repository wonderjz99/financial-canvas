#!/usr/bin/env python3
"""Prepare one SEC issuer, research its gaps, then build one offline HTML."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from financial_visualizer.exporting import ExportError, render_single_html
from financial_visualizer.providers import ReportError
from financial_visualizer.report_v2 import build_workspace, prepare


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare", help="Resolve a ticker and create a research workspace")
    p.add_argument("--symbol", required=True)
    p.add_argument("--data-root", type=Path)
    p.add_argument("--workspace", type=Path)
    p.add_argument("--user-agent", default=os.environ.get("SEC_USER_AGENT"))
    p.add_argument("--refresh", action="store_true", help="Fetch new SEC versions; retain a verified cache on failure")
    p.add_argument("--offline", action="store_true", help="Prepare using verified V2 cache only")
    p.add_argument("--skip-filings", action="store_true", help="Defer annual filing HTML and inline XBRL to the research step")
    b = commands.add_parser("build", help="Validate a prepared workspace and export; never uses the network")
    b.add_argument("--workspace", type=Path, required=True)
    b.add_argument("--output", type=Path)
    b.add_argument("--overwrite", action="store_true", help="Explicitly replace an existing output file")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            if args.offline and args.refresh:
                raise ReportError("options_conflict", "--offline and --refresh are mutually exclusive.")
            result = prepare(args.symbol, data_root=args.data_root, workspace=args.workspace, user_agent=args.user_agent,
                             offline=args.offline, refresh=args.refresh, skip_filings=args.skip_filings)
        else:
            report, registry, checks = build_workspace(args.workspace)
            output = args.output or ROOT / "reports" / (report["symbol"] + ".html")
            if output.exists() and not args.overwrite:
                raise ReportError("output_exists", "Output exists; choose another path or use --overwrite: " + str(output))
            document = render_single_html(report, registry)
            output.parent.mkdir(parents=True, exist_ok=True)
            if args.overwrite:
                # Prepare fully before an atomic replacement; failures preserve the existing report.
                with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".fv-", suffix=".tmp", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(document.encode("utf-8"))
                try:
                    temporary.replace(output)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                with output.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(document)
            result = {"output": str(output.resolve()), "symbol": report["symbol"], "years": report["years"],
                      "status": checks["status"], "bytes": len(document.encode("utf-8")), "checks": str((args.workspace / "checks.json").resolve())}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ReportError, ExportError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": getattr(exc, "code", "input_invalid"), "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
