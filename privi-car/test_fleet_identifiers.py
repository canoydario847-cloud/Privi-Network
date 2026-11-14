"""Regression checks for invalid fleet demo vehicle identifiers (offline only)."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent

class FleetIdentifierTests(unittest.TestCase):
    def check_rejected(self, identifier):
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "fleet.csv"
            output = pathlib.Path(directory) / "receipts.json"
            source.write_text("vehicle_id,odometer_km,consent\n" + identifier + ",100,yes\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(HERE / "fleet_batch.py"), str(source), str(output)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            import json
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(document["accepted"], 0)
            self.assertEqual(len(document["rejected"]), 1)

    def test_prefix_only_is_rejected(self):
        self.check_rejected("demo-")

    def test_oversized_identifier_is_rejected(self):
        self.check_rejected("demo-" + "x" * 76)

if __name__ == "__main__":
    unittest.main()
