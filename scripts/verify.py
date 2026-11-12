"""Run portable offline checks without changing the delivered HTML or snapshots."""

from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_public import public_profile, check_candidate


def run(command):
    subprocess.run(command, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('full', 'v2'), default='v2' if public_profile(ROOT) else 'full',
                        help='Public packages default to v2; the research repository defaults to full')
    parser.add_argument('--browser', action='store_true', help='Also run the installed Playwright browser suite')
    args = parser.parse_args()
    if args.scope == 'v2':
        for pattern in ('test_report_v2.py', 'test_public_profile.py'):
            run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', pattern, '-q'])
        if public_profile(ROOT):
            check_candidate(ROOT)
            if (ROOT / '.git').exists():
                check_candidate(ROOT, tracked=True, history=True)
    else:
        run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q'])
        with tempfile.TemporaryDirectory(prefix='fv-verify-') as directory:
            output = Path(directory) / 'report.html'
            run([sys.executable, '-B', 'scripts/build_html.py', '--output', str(output),
                 '--data-root', str(Path(directory) / 'cache')])
            # Universal-newline reads allow a Windows build while evidence stays byte-exact.
            if output.read_text(encoding='utf-8') != (ROOT / '财务动态图.html').read_text(encoding='utf-8'):
                raise SystemExit('Delivered HTML is stale; run scripts/build_html.py and review the change.')
    node = shutil.which('node')
    if node:
        for name in ('app.js', 'charts.js', 'single-company.js'):
            run([node, '--check', str(ROOT / 'web' / name)])
    else:
        print('Node.js unavailable; JavaScript syntax checks skipped. CI runs these checks.')
    if args.browser:
        npm = shutil.which('npm')
        if not npm:
            raise SystemExit('Browser checks require Node.js and npm; see docs/development.md.')
        # .cmd shims need a shell on Windows; no untrusted arguments are interpolated.
        subprocess.run([npm, 'run', 'test:browser'], cwd=ROOT, check=True,
                       shell=sys.platform == 'win32', env={**os.environ, 'FV_PYTHON': sys.executable, 'FV_TEST_SCOPE': args.scope})
    print(f'Offline verification passed ({args.scope}).')


if __name__ == '__main__':
    main()
