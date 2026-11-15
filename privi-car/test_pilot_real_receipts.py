"""Real receipt integration checks for Privi Car pilot summary.

Run: python3 -m unittest discover -s privi-car -p 'test_pilot_real_receipts.py'
No mocks, external dependencies, vehicles, or network access.
"""
import hashlib
import json
import unittest

from fleet_pilot_summary import summarize


def sample_receipt(km=12000):
    event = {
        "schema": "privi-car-consent-receipt-v1",
        "vehicle_pseudonym": "a" * 64,
        "event_type": "odometer_observation",
        "odometer_km": km,
        "consent": {"granted": True, "purpose": "maintenance_demo", "scope": ["odometer_km"]},
        "recorded_at": "2026-11-15T00:00:00Z",
        "mode": "LOCAL_DEMO_NOT_ON_CHAIN",
    }
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {"event": event, "sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def export_for(receipts, rejected=None):
    return {
        "mode": "LOCAL_DEMO_NOT_ON_CHAIN",
        "accepted": len(receipts),
        "receipts": receipts,
        "rejected": [] if rejected is None else rejected,
    }


class RealReceiptPilotTests(unittest.TestCase):
    def test_genuine_demo_hash_passes(self):
        result = summarize(export_for([sample_receipt()]))
        self.assertEqual(result["verified_receipts"], 1)
        self.assertFalse(result["requires_operator_review"])
        self.assertFalse(result["production_ready"])

    def test_tampered_mileage_triggers_review(self):
        receipt = sample_receipt()
        receipt["event"]["odometer_km"] = 99999
        result = summarize(export_for([receipt]))
        self.assertEqual(result["failed_verification"], 1)
        self.assertEqual(result["review_reasons"], ["receipt_integrity_failure"])

    def test_rejected_row_and_tampering_both_flagged(self):
        receipt = sample_receipt()
        receipt["event"]["odometer_km"] += 1
        result = summarize(export_for([receipt], [{"line": 2, "reason": "no consent"}]))
        self.assertEqual(result["review_reasons"], ["receipt_integrity_failure", "rejected_input_rows"])
        self.assertEqual(result["submitted"], 2)

    def test_summary_does_not_include_pseudonym(self):
        receipt = sample_receipt()
        result = summarize(export_for([receipt]))
        self.assertNotIn("a" * 64, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
