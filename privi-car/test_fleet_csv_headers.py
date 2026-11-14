"""CLI regression tests: malformed fleet CSV headers must never produce receipts."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

SCRIPT = pathlib.Path(__file__).with_name("fleet_batch.py")


class FleetCsvHeaderTests(unittest.TestCase):
    def run_csv(self, csv_text):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "input.csv"
            output = pathlib.Path(directory) / "receipts.json"
            source.write_text(csv_text, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(source), str(output)],
                capture_output=True, text=True, timeout=10
            )
            return proc, output.exists()

    def test_duplicate_consent_header_rejected(self):
        result, created = self.run_csv(
            "vehicle_id,odometer_km,consent,consent\n"
            "demo-van,100,no,yes\n"
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(created)
        self.assertIn("CSV header", result.stderr)

    def test_duplicate_vehicle_id_header_rejected(self):
        result, created = self.run_csv(
            "vehicle_id,vehicle_id,odometer_km,consent\n"
            "VIN-123,demo-van,100,yes\n"
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(created)

    def test_empty_csv_rejected(self):
        result, created = self.run_csv("")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(created)


if __name__ == "__main__":
    unittest.main()
