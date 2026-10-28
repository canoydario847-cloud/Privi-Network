import json
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from mainnet_gate import check, REQUIRED, valid_evidence_url

VALID_REPORT = "https://review.audit-domain.org/reports/prvi-genesis"

class GateTests(unittest.TestCase):
    def test_missing_evidence_blocks(self):
        self.assertTrue(check({"network": "privi-native-mainnet", "asset": "PRVI", "gates": {}}))
    def test_wrong_network_blocks(self):
        self.assertTrue(check({"network": "local-4221", "asset": "PRVI", "gates": {}}))
    def test_complete_review_record(self):
        gates = {name: {"status": "verified", "evidence_url": VALID_REPORT, "reviewer": "independent reviewer"} for name in REQUIRED}
        self.assertEqual(check({"network": "privi-native-mainnet", "asset": "PRVI", "gates": gates}), [])
    def test_missing_reviewer_blocks(self):
        gates = {name: {"status": "verified", "evidence_url": VALID_REPORT, "reviewer": ""} for name in REQUIRED}
        self.assertTrue(check({"network": "privi-native-mainnet", "asset": "PRVI", "gates": gates}))

    def test_valid_evidence_report_url(self):
        self.assertTrue(valid_evidence_url(VALID_REPORT))

    def test_invalid_evidence_urls_block(self):
        invalid = [
            None, "", "https://", "https:///report", "http://reviews.org/report",
            "https://example.org/review", "https://localhost/reports/123",
            "https://review.example/reports/123", "https://review.test/reports/123",
            "https://review.audit-domain.org",
            "https://user:pass@review.audit-domain.org/report",
            "https://review.audit-domain.org/report#secret",
            "https://review.audit-domain.org:bad/report",
            "https://review.audit-domain.org/report\n",
            "https://review.audit-domain.org/\treport",
        ]
        for url in invalid:
            with self.subTest(url=url):
                self.assertFalse(valid_evidence_url(url))

    def test_rejects_private_and_ip_literal_evidence_urls(self):
        blocked = [
            "https://127.0.0.1/report",
            "https://127.1/report",
            "https://10.0.0.1/report",
            "https://192.168.1.7/report",
            "https://169.254.169.254/latest/meta-data",
            "https://8.8.8.8/report",
            "https://[::1]/report",
            "https://[fe80::1]/report",
            "https://0x7f.0.0.1/report",
            "https://review.internal/report",
            "https://review.home.arpa/report",
            "https://review.lan/report",
            "https://review.onion/report",
            "https://review/report",
        ]
        for url in blocked:
            with self.subTest(url=url):
                self.assertFalse(valid_evidence_url(url))

    def test_public_report_domain_remains_valid(self):
        self.assertTrue(valid_evidence_url(
            "https://github.com/example-security-team/reports/blob/main/assessment.pdf"
        ))

    def test_all_gates_reject_example_placeholder(self):
        gates = {
            name: {
                "status": "verified",
                "evidence_url": "https://example.org/review",
                "reviewer": "reviewer",
            } for name in REQUIRED
        }
        errors = check({"network": "privi-native-mainnet", "asset": "PRVI", "gates": gates})
        self.assertEqual(len(errors), len(REQUIRED))

    def test_cli_never_authorizes_mainnet_even_with_self_declared_verified_links(self):
        # Complete shape is not proof of chain security or operational readiness.
        gates = {
            name: {
                "status": "verified",
                "evidence_url": VALID_REPORT,
                "reviewer": "claimed independent reviewer",
            } for name in REQUIRED
        }
        document = {"network": "privi-native-mainnet", "asset": "PRVI", "gates": gates}
        self.assertEqual(check(document), [])  # Presence-only checks can pass.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "untrusted-evidence.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("mainnet_gate.py")), str(path)],
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("NO-GO", result.stdout)
        self.assertIn("independent live verification", result.stdout)


if __name__ == "__main__":
    unittest.main()
