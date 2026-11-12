"""Synthetic checks for license, file boundaries and forbidden historical paths."""
import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.check_public import PROFILE, PublicationError, check_candidate, permitted_file, public_profile, validate_relative


class PublicProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.marker = {"schemaVersion": "1.0", "profile": PROFILE, "license": "MIT", "includesResearchHistory": False}
        self.write("PUBLIC_RELEASE.json", json.dumps(self.marker))
        for name in ["THIRD_PARTY_NOTICES.md", "README.md", "scripts/report.py", "scripts/verify.py", "tests/test_report_v2.py", "tests/browser/v2.spec.cjs"]:
            self.write(name, "Synthetic publication fixture\n")
        self.write("LICENSE", "MIT License\n\nCopyright (c) 2026 wonderjz99\n")

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def git(self, *args):
        return subprocess.check_output(["git", "-c", "user.name=Synthetic Test", "-c", "user.email=test@example.invalid", *args], cwd=self.root, stderr=subprocess.DEVNULL)

    def test_valid_synthetic_public_profile(self):
        self.assertTrue(public_profile(self.root))
        self.assertEqual(check_candidate(self.root)["license"], "MIT")
        permitted_file("financial_visualizer/core.py")
        permitted_file("web/index.html")

    def test_rejects_raw_data_reports_and_private_configuration(self):
        for relative in ["data/probes/issuer.json", "reports/COST.html", "财务动态图.html", "examples/old.html", "config/issuers.json", "settings/.env", "key.pem", ".ssh/id_rsa", "__pycache__/cache.pyc"]:
            with self.subTest(path=relative), self.assertRaises(PublicationError):
                permitted_file(relative)

    def test_paths_cannot_escape_or_disguise_components(self):
        for relative in ["../secret", "/secret", "C:/secret", "a/../secret", "a\\secret", "a//b", "a\nb", "./a"]:
            with self.subTest(path=relative), self.assertRaises(PublicationError):
                validate_relative(relative)

    def test_declared_history_or_wrong_license_is_rejected(self):
        for key, value in [("includesResearchHistory", True), ("license", "unknown")]:
            marker = {**self.marker, key: value}
            self.write("PUBLIC_RELEASE.json", json.dumps(marker))
            with self.subTest(key=key), self.assertRaises(PublicationError):
                check_candidate(self.root)

    def test_untracked_historical_data_is_rejected(self):
        self.write("data/old-source.json", "{}")
        with self.assertRaises(PublicationError):
            check_candidate(self.root)

    def test_forced_tracked_runtime_data_is_rejected(self):
        self.git("init", "-q")
        self.write(".local/saved.json", "{}")
        self.git("add", ".")
        with self.assertRaises(PublicationError):
            check_candidate(self.root, tracked=True)

    def test_deleted_historical_vendor_files_are_still_rejected(self):
        self.git("init", "-q")
        self.write("data/vendor-response.json", "{}")
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic history boundary fixture")
        self.git("rm", "-q", "data/vendor-response.json")
        self.git("commit", "-qm", "Synthetic deletion fixture")
        check_candidate(self.root, tracked=True)
        with self.assertRaises(PublicationError):
            check_candidate(self.root, tracked=True, history=True)

    def test_clean_git_history_passes(self):
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic clean initial fixture")
        self.assertGreater(check_candidate(self.root, tracked=True, history=True)["historyPathsChecked"], 0)

    def example(self, source="SEC", extra_company=False):
        report = {"schemaVersion": "1.0", "symbol": "COST", "years": [2026], "company": {"currency": "USD"},
                  "snapshot": {"asOf": "2026-11-12"}, "facts": {"synthetic": {"source": source, "sourceUrl": "https://www.sec.gov/Archives/edgar/data/123456/annual.html"}}}
        registry = {"COST": report}
        if extra_company:
            registry["PDD"] = report
        body = 'window.__FV_REPORTS__=' + json.dumps(registry) + ';window.__FV_REPORT__=null;window.__FV_OFFLINE__=true;'
        self.write("examples/reports/COST.html", body)
        record = {"path": "examples/reports/COST.html", "symbol": "COST", "years": [2026], "currency": "USD", "asOf": "2026-11-12",
                  "factSources": [source], "sha256": hashlib.sha256(body.encode()).hexdigest()}
        self.write("examples/provenance.json", json.dumps({"schemaVersion": "1.0", "reports": [record]}))

    def test_reviewed_official_example_is_checked_in_nested_report_directory(self):
        self.example()
        self.assertEqual(check_candidate(self.root)["reviewedReports"], 1)
        with self.assertRaises(PublicationError):
            permitted_file("examples/reports/PDD.html")

    def test_example_rejects_vendor_data_and_additional_companies(self):
        for source, extra in [("Futu", False), ("SEC", True)]:
            self.example(source, extra)
            with self.subTest(source=source, extra=extra), self.assertRaises(PublicationError):
                check_candidate(self.root)

    def test_example_provenance_hash_cannot_be_bypassed(self):
        self.example()
        self.write("examples/reports/COST.html", "Changed after provenance review")
        with self.assertRaises(PublicationError):
            check_candidate(self.root)

    def test_replaced_vendor_example_is_still_rejected_in_history(self):
        self.git("init", "-q")
        self.example("Futu")
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic bad example fixture")
        self.example("SEC")
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic replacement fixture")
        check_candidate(self.root, tracked=True)
        with self.assertRaises(PublicationError):
            check_candidate(self.root, tracked=True, history=True)


if __name__ == "__main__":
    unittest.main()
