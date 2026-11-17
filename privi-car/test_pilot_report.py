"""Regression tests for privacy-safe Privi Car customer pilot report."""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest

from consent_receipt_demo import make_receipt
from fleet_odometer_audit import audit
from pilot_report import main, render_report


def export(*receipts, rejected=None):
    return {"mode": "LOCAL_DEMO_NOT_ON_CHAIN", "accepted": len(receipts),
            "receipts": list(receipts), "rejected": rejected or []}


class PilotReportTests(unittest.TestCase):
    def test_clean_export_is_not_called_vehicle_verified(self):
        report = render_report(audit(export(make_receipt("private-car-1", 123456, True))))
        self.assertIn("NO ANOMALIES FOUND IN SUBMITTED RECORDS", report)
        self.assertIn("not verified vehicle telemetry", report)
        self.assertIn("does not authenticate vehicle origin", report)
        self.assertNotIn("private-car-1", report)
        self.assertNotIn("123456", report)

    def test_invalid_hash_flags_review(self):
        record = make_receipt("private-car-2", 234567, True)
        record["event"]["odometer_km"] = 1
        report = render_report(audit(export(record)))
        self.assertIn("HUMAN REVIEW RECOMMENDED", report)
        self.assertIn("Invalid receipts: 1", report)
        self.assertNotIn("private-car-2", report)
        self.assertNotIn("234567", report)

    def test_rejected_no_consent_flags_review(self):
        report = render_report(audit(export(rejected=[{"reason": "no consent"}])))
        self.assertIn("Rejected input rows: 1", report)
        self.assertIn("HUMAN REVIEW RECOMMENDED", report)
        self.assertNotIn("no consent", report)

    def test_reject_arbitrary_untrusted_summary(self):
        with self.assertRaises(ValueError):
            render_report({"status": "production_ready"})

    def test_reject_invalid_count_type(self):
        summary = audit(export())
        summary["receipt_count"] = True
        with self.assertRaises(ValueError):
            render_report(summary)

    def test_reject_negative_count(self):
        summary = audit(export())
        summary["duplicate_receipt_count"] = -1
        with self.assertRaises(ValueError):
            render_report(summary)

    def test_reject_nonboolean_review_flag(self):
        summary = audit(export())
        summary["requires_operator_review"] = "false"
        with self.assertRaises(ValueError):
            render_report(summary)

    def test_cli_stdout(self):
        with tempfile.TemporaryDirectory() as folder:
            source = pathlib.Path(folder) / "demo.json"
            source.write_text(json.dumps(export()), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([str(source)]), 0)
            self.assertIn("Receipts reviewed: 0", output.getvalue())

    def test_cli_writes_local_text_report(self):
        with tempfile.TemporaryDirectory() as folder:
            source = pathlib.Path(folder) / "demo.json"
            target = pathlib.Path(folder) / "pilot.txt"
            source.write_text(json.dumps(export()), encoding="utf-8")
            self.assertEqual(main([str(source), "--output", str(target)]), 0)
            self.assertIn("OFFLINE MILEAGE", target.read_text())

    def test_cli_rejects_overwriting_input(self):
        with tempfile.TemporaryDirectory() as folder:
            source = pathlib.Path(folder) / "demo.txt"
            original = json.dumps(export())
            source.write_text(original, encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(source), "--output", str(source)]), 2)
            self.assertEqual(source.read_text(), original)

    def test_cli_rejects_non_txt_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            source = pathlib.Path(folder) / "demo.json"
            source.write_text(json.dumps(export()), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(source), "--output",
                                       str(pathlib.Path(folder) / "pilot.json")]), 2)

    def test_cli_rejects_live_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            source = pathlib.Path(folder) / "demo.json"
            source.write_text(json.dumps({"mode": "LIVE", "accepted": 0,
                                          "receipts": [], "rejected": []}))
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(source)]), 2)


if __name__ == "__main__":
    unittest.main()
