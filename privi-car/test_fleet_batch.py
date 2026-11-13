"""Run: python3 -m unittest discover -s privi-car -p 'test_*.py'"""
import unittest
from fleet_batch import process_rows
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

    def test_unexpected_csv_fields(self):
        with self.assertRaises(ValueError):
            process_rows([{"vehicle_id": "demo-x", "odometer_km": "1", "consent": "yes", "driver_name": "X"}])
