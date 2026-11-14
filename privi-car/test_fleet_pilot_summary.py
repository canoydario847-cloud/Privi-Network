"""Offline pilot summary regression tests. Run: python3 -m unittest discover -s privi-car -p 'test_fleet_pilot_summary.py'"""
import unittest
from unittest.mock import patch
from fleet_pilot_summary import summarize


class PilotSummaryTests(unittest.TestCase):
    def test_counts_without_disclosing_vehicle_ids(self):
        export = {"mode": "LOCAL_DEMO_NOT_ON_CHAIN", "accepted": 1,
                  "receipts": [{"vehicle_id": "demo-secret"}],
                  "rejected": [{"line": 3, "reason": "no explicit consent"}]}
        with patch("fleet_pilot_summary.verify_receipt", return_value=(True, "ok")):
            result = summarize(export)
        self.assertEqual((result["submitted"], result["verified_receipts"], result["rejected_rows"]), (2, 1, 1))
        self.assertNotIn("demo-secret", str(result))
        self.assertFalse(result["production_ready"])

    def test_detects_failed_verification(self):
        export = {"mode": "LOCAL_DEMO_NOT_ON_CHAIN", "accepted": 1, "receipts": [{}], "rejected": []}
        with patch("fleet_pilot_summary.verify_receipt", return_value=(False, "tampered")):
            self.assertEqual(summarize(export)["failed_verification"], 1)

    def test_rejects_inconsistent_counts(self):
        export = {"mode": "LOCAL_DEMO_NOT_ON_CHAIN", "accepted": 2, "receipts": [{}], "rejected": []}
        with self.assertRaises(ValueError):
            summarize(export)


if __name__ == "__main__":
    unittest.main()
