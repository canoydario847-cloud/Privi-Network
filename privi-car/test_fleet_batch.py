"""Run: python3 -m unittest discover -s privi-car -p 'test_*.py'"""
import unittest
import contextlib
import io
import pathlib
import tempfile
from unittest.mock import patch
from fleet_batch import main, process_rows
from verify_receipt import verify_receipt


class FleetBatchTests(unittest.TestCase):
    def test_opt_in_batch_and_verify(self):
        data = process_rows([
            {"vehicle_id": "demo-van-1", "odometer_km": "1234", "consent": "yes"},
            {"vehicle_id": "demo-van-2", "odometer_km": "4567", "consent": "no"},
        ])
        self.assertEqual(data["accepted"], 1)
        self.assertEqual(len(data["rejected"]), 1)
        self.assertTrue(verify_receipt(data["receipts"][0])[0])

    def test_invalid_rows_rejected(self):
        data = process_rows([
            {"vehicle_id": "VIN123", "odometer_km": "10", "consent": "yes"},
            {"vehicle_id": "demo-van", "odometer_km": "-1", "consent": "yes"},
            {"vehicle_id": "demo-van", "odometer_km": "10", "consent": "true"},
        ])
        self.assertEqual(data["accepted"], 0)
        self.assertEqual(len(data["rejected"]), 3)


    def test_export_refuses_overwriting_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            src = pathlib.Path(folder) / "consented.csv"
            dest = pathlib.Path(folder) / "existing.json"
            src.write_text("vehicle_id,odometer_km,consent\ndemo-van-1,1234,yes\n", encoding="utf-8")
            dest.write_text("PREVIOUS CUSTOMER EXPORT", encoding="utf-8")
            with patch("sys.argv", ["fleet_batch.py", str(src), str(dest)]):
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(), 2)
            self.assertEqual(dest.read_text(encoding="utf-8"), "PREVIOUS CUSTOMER EXPORT")

    def test_export_creates_new_file(self):
        with tempfile.TemporaryDirectory() as folder:
            src = pathlib.Path(folder) / "consented.csv"
            dest = pathlib.Path(folder) / "new.json"
            src.write_text("vehicle_id,odometer_km,consent\ndemo-van-1,1234,yes\n", encoding="utf-8")
            with patch("sys.argv", ["fleet_batch.py", str(src), str(dest)]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
            self.assertTrue(dest.is_file())

    def test_unexpected_csv_fields(self):
        with self.assertRaises(ValueError):
            process_rows([{"vehicle_id": "demo-x", "odometer_km": "1", "consent": "yes", "driver_name": "X"}])
