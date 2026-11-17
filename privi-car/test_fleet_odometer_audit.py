"""Offline-only aggregate fleet audit regression tests."""
import copy
import datetime
import importlib.util
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
from consent_receipt_demo import make_receipt
from fleet_odometer_audit import audit


def export(*receipts, rejected=None):
    return {"mode": "LOCAL_DEMO_NOT_ON_CHAIN", "accepted": len(receipts),
            "receipts": list(receipts), "rejected": rejected or []}


def at(vehicle, km, when):
    with patch("consent_receipt_demo.datetime.datetime") as mocked:
        mocked.now.return_value = when
        mocked.timezone = datetime.timezone
        return make_receipt(vehicle, km, True)


def receipt(vehicle, km, timestamp):
    obj = make_receipt(vehicle, km, True)
    obj["event"]["recorded_at"] = timestamp
    import hashlib
    obj["sha256"] = hashlib.sha256(
        json.dumps(obj["event"], sort_keys=True,
                   separators=(",", ":")).encode()).hexdigest()
    return obj


class FleetOdometerAuditTests(unittest.TestCase):
    def test_clean_sequence(self):
        a = receipt("car1", 100, "2026-11-01T00:00:00+00:00")
        b = receipt("car1", 120, "2026-11-02T00:00:00+00:00")
        result = audit(export(b, a))
        self.assertEqual(result["verified_receipt_count"], 2)
        self.assertEqual(result["vehicle_pseudonym_count"], 1)
        self.assertFalse(result["requires_operator_review"])

    def test_rollback(self):
        a = receipt("car1", 200, "2026-11-01T00:00:00+00:00")
        b = receipt("car1", 150, "2026-11-02T00:00:00+00:00")
        result = audit(export(a, b))
        self.assertEqual(result["odometer_decrease_count"], 1)
        self.assertTrue(result["requires_operator_review"])

    def test_duplicate(self):
        a = make_receipt("car1", 200, True)
        result = audit(export(a, copy.deepcopy(a)))
        self.assertEqual(result["duplicate_receipt_count"], 1)
        self.assertTrue(result["requires_operator_review"])

    def test_same_time_conflict(self):
        a = receipt("car1", 200, "2026-11-01T00:00:00+00:00")
        b = receipt("car1", 300, "2026-11-01T00:00:00+00:00")
        result = audit(export(a, b))
        self.assertEqual(result["same_timestamp_conflict_count"], 1)

    def test_timezone_normalization(self):
        a = receipt("car1", 200, "2026-11-01T10:00:00+02:00")
        b = receipt("car1", 190, "2026-11-01T09:00:00+00:00")
        self.assertEqual(audit(export(a, b))["odometer_decrease_count"], 1)

    def test_separate_vehicles_not_compared(self):
        a = receipt("car1", 200, "2026-11-01T00:00:00+00:00")
        b = receipt("car2", 100, "2026-11-02T00:00:00+00:00")
        self.assertFalse(audit(export(a, b))["requires_operator_review"])

    def test_tampered_hash_not_counted(self):
        a = make_receipt("car1", 200, True)
        a["event"]["odometer_km"] = 123
        result = audit(export(a))
        self.assertEqual(result["invalid_receipt_count"], 1)
        self.assertEqual(result["vehicle_pseudonym_count"], 0)
        self.assertTrue(result["requires_operator_review"])

    def test_rejected_input_triggers_review(self):
        result = audit(export(rejected=[{"reason": "no consent"}]))
        self.assertEqual(result["rejected_input_row_count"], 1)
        self.assertTrue(result["requires_operator_review"])

    def test_malformed_envelopes(self):
        for value in (None, [], 4, {"event": [], "sha256": "x"}):
            with self.subTest(value=value):
                self.assertEqual(audit(export(value))["invalid_receipt_count"], 1)

    def test_wrong_mode(self):
        with self.assertRaises(ValueError):
            audit({"mode": "LIVE", "accepted": 0, "receipts": [], "rejected": []})

    def test_boolean_accepted_count(self):
        with self.assertRaises(ValueError):
            audit({"mode": "LOCAL_DEMO_NOT_ON_CHAIN", "accepted": True,
                   "receipts": [make_receipt("car1", 1, True)], "rejected": []})

    def test_missing_lists(self):
        with self.assertRaises(ValueError):
            audit({"mode": "LOCAL_DEMO_NOT_ON_CHAIN", "accepted": 0})

    def test_no_identity_or_mileage_in_report(self):
        result = audit(export(make_receipt("private-vehicle-name", 123456, True)))
        raw = json.dumps(result)
        self.assertNotIn("private-vehicle-name", raw)
        self.assertNotIn("123456", raw)
        self.assertNotIn("vehicle_pseudonym", str(result.get("vehicle_pseudonym_count", "")))
        self.assertFalse(result["production_ready"])

    def test_empty_export(self):
        result = audit(export())
        self.assertEqual(result["verified_receipt_count"], 0)
        self.assertFalse(result["requires_operator_review"])


if __name__ == "__main__":
    unittest.main()
