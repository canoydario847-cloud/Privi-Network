import json
import tempfile
import unittest
from pathlib import Path
from mainnet_gate import check, REQUIRED

class GateTests(unittest.TestCase):
    def test_missing_evidence_blocks(self):
        self.assertTrue(check({"network": "privi-native-mainnet", "asset": "PRVI", "gates": {}}))
    def test_wrong_network_blocks(self):
        self.assertTrue(check({"network": "local-4221", "asset": "PRVI", "gates": {}}))
    def test_complete_review_record(self):
        gates = {name: {"status": "verified", "evidence_url": "https://example.org/review", "reviewer": "independent reviewer"} for name in REQUIRED}
        self.assertEqual(check({"network": "privi-native-mainnet", "asset": "PRVI", "gates": gates}), [])
    def test_missing_reviewer_blocks(self):
        gates = {name: {"status": "verified", "evidence_url": "https://example.org/review", "reviewer": ""} for name in REQUIRED}
        self.assertTrue(check({"network": "privi-native-mainnet", "asset": "PRVI", "gates": gates}))

if __name__ == "__main__":
    unittest.main()
