import unittest
from unittest.mock import patch
from verify_fleet_export import verify_export


class FleetExportVerifierTests(unittest.TestCase):
    def setUp(self):
        self.example = {"mode": "LOCAL_DEMO_NOT_ON_CHAIN", "accepted": 1, "rejected": [], "receipts": [{"event": {}, "sha256": "demo"}]}

    def test_valid_export(self):
        with patch("verify_fleet_export.verify_receipt", return_value=(True, "ok")):
            self.assertTrue(verify_export(self.example)[0])

    def test_reject_count_tampering(self):
        self.example["accepted"] = 2
        self.assertFalse(verify_export(self.example)[0])

    def test_reject_receipt_tampering(self):
        with patch("verify_fleet_export.verify_receipt", return_value=(False, "changed hash")):
            self.assertFalse(verify_export(self.example)[0])

    def test_reject_extra_personal_fields(self):
        self.example["driver_name"] = "Someone"
        self.assertFalse(verify_export(self.example)[0])

    def test_reject_invalid_rejection_metadata(self):
        self.example["rejected"] = [{"line": 1, "reason": "no consent"}]
        with patch("verify_fleet_export.verify_receipt", return_value=(True, "ok")):
            self.assertFalse(verify_export(self.example)[0])


if __name__ == "__main__":
    unittest.main()
