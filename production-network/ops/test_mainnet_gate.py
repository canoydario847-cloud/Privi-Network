import json
import tempfile
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

if __name__ == "__main__":
    unittest.main()
