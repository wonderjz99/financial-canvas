"""Create a small synthetic V2 browser fixture without network or legacy sources."""
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_report_v2 import inputs
from financial_visualizer.exporting import render_single_html
from financial_visualizer.report_v2 import build_workspace, prepare
from financial_visualizer.sec_cache import SecCache, sha


def main():
    _, submissions, raw, _ = inputs()
    destination = ROOT / '.local' / 'browser'
    workspace = destination / 'v2-workspace'
    if workspace.exists():
        shutil.rmtree(workspace)
    def get(cache, url, validator):
        data = {'fields': ['cik', 'ticker'], 'data': [[123456, 'NEW']]} if 'company_tickers' in url else raw if 'companyfacts' in url else submissions
        body = json.dumps(data).encode()
        validator(body)
        return body, {'url': url, 'sha256': sha(body), 'version': sha(body), 'retrievedAt': '2026-11-01T00:00:00+00:00', 'mode': 'fixture'}
    with patch.object(SecCache, 'get', get):
        prepare('NEW', workspace=workspace, skip_filings=True)
    report, registry, _ = build_workspace(workspace)
    (destination / 'v2.html').write_text(render_single_html(report, registry), encoding='utf-8')


if __name__ == '__main__':
    main()
