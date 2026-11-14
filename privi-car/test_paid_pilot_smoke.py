"""Integration smoke test for a potential paid Privi Car fleet records pilot.

Run: python3 -m unittest discover -s privi-car -p 'test_paid_pilot_smoke.py' -v
No network, vehicle, wallet, blockchain, or paid service is used.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent


class PaidPilotSmokeTests(unittest.TestCase):
    def run_script(self, script, *args):
        return subprocess.run(
            [sys.executable, str(HERE / script), *(str(a) for a in args)],
            capture_output=True, text=True, timeout=15,
        )

    def test_consent_and_verified_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source, output = root / "fleet.csv", root / "receipts.json"
            source.write_text(
                "vehicle_id,odometer_km,consent\n"
                "demo-van-01,12000,yes\n"
                "demo-van-02,34000,no\n"
                "demo-van-03,60000,yes\n",
                encoding="utf-8",
            )
            generated = self.run_script("fleet_batch.py", source, output)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            doc = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(doc["mode"], "LOCAL_DEMO_NOT_ON_CHAIN")
            self.assertEqual(doc["accepted"], 2)
            self.assertEqual(len(doc["rejected"]), 1)
            self.assertEqual(len(doc["receipts"]), 2)
            self.assertNotIn("demo-van-01", output.read_text())
            self.assertNotIn("demo-van-03", output.read_text())
            verified = self.run_script("verify_fleet_export.py", output)
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

            # Altering a mileage observation must invalidate its receipt hash.
            doc["receipts"][0]["event"]["odometer_km"] = 99999
            output.write_text(json.dumps(doc), encoding="utf-8")
            tampered = self.run_script("verify_fleet_export.py", output)
            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("invalid", tampered.stdout.lower())

    def test_no_consent_means_no_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source, output = root / "fleet.csv", root / "receipts.json"
            source.write_text(
                "vehicle_id,odometer_km,consent\ndemo-van-01,12000,no\n",
                encoding="utf-8",
            )
            generated = self.run_script("fleet_batch.py", source, output)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            doc = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(doc["accepted"], 0)
            self.assertEqual(doc["receipts"], [])
            self.assertEqual(len(doc["rejected"]), 1)

    def test_duplicate_consent_column_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source, output = root / "fleet.csv", root / "receipts.json"
            source.write_text(
                "vehicle_id,odometer_km,consent,consent\ndemo-van-01,12000,no,yes\n",
                encoding="utf-8",
            )
            generated = self.run_script("fleet_batch.py", source, output)
            self.assertNotEqual(generated.returncode, 0)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
