"""Revenue-first offline pilot: CSV consent -> receipts -> aggregate report.

No real vehicle, customer, network, blockchain, or payment involved.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent


def run(name, *args):
    return subprocess.run(
        [sys.executable, str(HERE / name), *(str(arg) for arg in args)],
        text=True, capture_output=True, timeout=15,
    )


class CustomerPilotPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.csv = self.root / "pilot.csv"
        self.export = self.root / "receipts.json"
        self.report = self.root / "customer-report.txt"

    def generate(self, csv_text):
        self.csv.write_text(csv_text, encoding="utf-8")
        return run("fleet_batch.py", self.csv, self.export)

    def test_consent_to_customer_report_excludes_identifiers(self):
        self.assertEqual(self.generate(
            "vehicle_id,odometer_km,consent\n"
            "demo-van-sensitive-001,12000,yes\n"
            "demo-van-sensitive-002,34000,no\n"
            "demo-van-sensitive-003,50000,yes\n"
        ).returncode, 0)
        result = run("pilot_report.py", self.export, "--output", self.report)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.report.read_text(encoding="utf-8")
        self.assertIn("Receipts reviewed: 2", text)
        self.assertIn("Rejected input rows: 1", text)
        self.assertIn("HUMAN REVIEW RECOMMENDED", text)
        self.assertNotIn("demo-van-sensitive", text)
        self.assertNotIn("12000", text)
        self.assertNotIn("50000", text)
        self.assertNotIn("34000", text)
        self.assertNotIn("vehicle_pseudonym\":", text)
        self.assertIn("not verified vehicle telemetry", text)
        self.assertIn("No live vehicle connection", text)

    def test_no_consent_produces_no_receipts_and_review_flag(self):
        self.assertEqual(self.generate(
            "vehicle_id,odometer_km,consent\n"
            "demo-van-sensitive-001,12000,no\n"
        ).returncode, 0)
        self.assertEqual(json.loads(self.export.read_text())["receipts"], [])
        result = run("pilot_report.py", self.export)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Receipts reviewed: 0", result.stdout)
        self.assertIn("Rejected input rows: 1", result.stdout)
        self.assertIn("HUMAN REVIEW RECOMMENDED", result.stdout)
        self.assertNotIn("demo-van-sensitive", result.stdout)

    def test_tampered_export_is_reported_not_accepted_as_valid(self):
        self.assertEqual(self.generate(
            "vehicle_id,odometer_km,consent\n"
            "demo-van-sensitive-001,12000,yes\n"
        ).returncode, 0)
        doc = json.loads(self.export.read_text())
        doc["receipts"][0]["event"]["odometer_km"] = 999999
        self.export.write_text(json.dumps(doc), encoding="utf-8")
        result = run("pilot_report.py", self.export)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Invalid receipts: 1", result.stdout)
        self.assertIn("Receipts with valid integrity hashes: 0", result.stdout)
        self.assertIn("HUMAN REVIEW RECOMMENDED", result.stdout)
        self.assertNotIn("999999", result.stdout)

    def test_second_customer_report_cannot_overwrite_first(self):
        self.assertEqual(self.generate(
            "vehicle_id,odometer_km,consent\n"
            "demo-van-sensitive-001,12000,yes\n"
        ).returncode, 0)
        first = run("pilot_report.py", self.export, "--output", self.report)
        self.assertEqual(first.returncode, 0, first.stderr)
        before = self.report.read_bytes()
        second = run("pilot_report.py", self.export, "--output", self.report)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(self.report.read_bytes(), before)

    def test_invalid_consent_header_rejected_without_report(self):
        self.assertNotEqual(self.generate(
            "vehicle_id,odometer_km,consent,consent\n"
            "demo-van-sensitive-001,12000,no,yes\n"
        ).returncode, 0)
        self.assertFalse(self.export.exists())
        self.assertFalse(self.report.exists())


if __name__ == "__main__":
    unittest.main()
