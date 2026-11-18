"""Customer-facing pilot report must reject contradictory aggregate audits."""
import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from pilot_report import render_report

BASE = {
    "status": "ADVISORY_ONLY_NOT_PROOF_OF_VEHICLE_ORIGIN",
    "receipt_count": 3,
    "verified_receipt_count": 2,
    "invalid_receipt_count": 1,
    "vehicle_pseudonym_count": 2,
    "odometer_decrease_count": 0,
    "same_timestamp_conflict_count": 0,
    "duplicate_receipt_count": 0,
    "vehicle_pseudonyms_flagged_count": 0,
    "rejected_input_row_count": 0,
    "requires_operator_review": True,
}


class ReportConsistencyTests(unittest.TestCase):
    def test_valid_report(self):
        report = render_report(BASE)
        self.assertIn("HUMAN REVIEW RECOMMENDED", report)
        self.assertNotIn("vehicle_id", report)

    def test_invalid_receipt_total(self):
        sample = copy.deepcopy(BASE)
        sample["invalid_receipt_count"] = 2
        with self.assertRaisesRegex(ValueError, "totals"):
            render_report(sample)

    def test_too_many_pseudonyms(self):
        sample = copy.deepcopy(BASE)
        sample["vehicle_pseudonym_count"] = 3
        with self.assertRaises(ValueError):
            render_report(sample)

    def test_too_many_flagged_vehicles(self):
        sample = copy.deepcopy(BASE)
        sample["vehicle_pseudonyms_flagged_count"] = 3
        with self.assertRaises(ValueError):
            render_report(sample)

    def test_excess_duplicate_count(self):
        sample = copy.deepcopy(BASE)
        sample["duplicate_receipt_count"] = 3
        with self.assertRaises(ValueError):
            render_report(sample)

    def test_excess_conflict_count(self):
        sample = copy.deepcopy(BASE)
        sample["same_timestamp_conflict_count"] = 3
        with self.assertRaises(ValueError):
            render_report(sample)

    def test_excess_decrease_count(self):
        sample = copy.deepcopy(BASE)
        sample["odometer_decrease_count"] = 3
        with self.assertRaises(ValueError):
            render_report(sample)

    def test_false_clean_report(self):
        sample = copy.deepcopy(BASE)
        sample["requires_operator_review"] = False
        with self.assertRaisesRegex(ValueError, "review flag"):
            render_report(sample)

    def test_false_review_warning(self):
        sample = copy.deepcopy(BASE)
        sample.update({
            "receipt_count": 2,
            "invalid_receipt_count": 0,
            "requires_operator_review": True,
        })
        with self.assertRaisesRegex(ValueError, "review flag"):
            render_report(sample)

    def test_boolean_count_rejected(self):
        sample = copy.deepcopy(BASE)
        sample["receipt_count"] = True
        with self.assertRaises(ValueError):
            render_report(sample)


if __name__ == "__main__":
    unittest.main()
