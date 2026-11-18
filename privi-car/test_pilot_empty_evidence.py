"""No consented valid evidence must never be presented as a clean vehicle review."""
import copy
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from pilot_report import render_report
from test_pilot_report_consistency import BASE


class EmptyPilotEvidenceTests(unittest.TestCase):
    def sample(self, **changes):
        value = copy.deepcopy(BASE)
        value.update({
            "receipt_count": 0,
            "verified_receipt_count": 0,
            "invalid_receipt_count": 0,
            "vehicle_pseudonym_count": 0,
            "odometer_decrease_count": 0,
            "same_timestamp_conflict_count": 0,
            "duplicate_receipt_count": 0,
            "vehicle_pseudonyms_flagged_count": 0,
            "rejected_input_row_count": 0,
            "requires_operator_review": False,
        })
        value.update(changes)
        return value

    def test_empty_export_does_not_claim_clean(self):
        report = render_report(self.sample())
        self.assertIn("INSUFFICIENT CONSENTED RECORDS", report)
        self.assertNotIn("NO ANOMALIES FOUND", report)
        self.assertIn("Request at least one consented", report)

    def test_all_invalid_receipts_are_not_clean(self):
        report = render_report(self.sample(
            receipt_count=2, invalid_receipt_count=2,
            requires_operator_review=True))
        self.assertIn("INSUFFICIENT CONSENTED RECORDS", report)
        self.assertNotIn("NO ANOMALIES FOUND", report)

    def test_only_rejected_nonconsent_rows_are_not_clean(self):
        report = render_report(self.sample(
            rejected_input_row_count=3, requires_operator_review=True))
        self.assertIn("INSUFFICIENT CONSENTED RECORDS", report)
        self.assertNotIn("NO ANOMALIES FOUND", report)

    def test_one_valid_receipt_without_flags_is_limited_clean(self):
        report = render_report(self.sample(
            receipt_count=1, verified_receipt_count=1,
            vehicle_pseudonym_count=1))
        self.assertIn("NO ANOMALIES FOUND IN SUBMITTED RECORDS", report)
        self.assertIn("not verified vehicle telemetry", report)
        self.assertNotIn("INSUFFICIENT CONSENTED RECORDS", report)

    def test_one_valid_receipt_with_rejections_needs_review(self):
        report = render_report(self.sample(
            receipt_count=1, verified_receipt_count=1,
            vehicle_pseudonym_count=1,
            rejected_input_row_count=1, requires_operator_review=True))
        self.assertIn("HUMAN REVIEW RECOMMENDED", report)
        self.assertNotIn("NO ANOMALIES FOUND", report)


if __name__ == "__main__":
    unittest.main()
