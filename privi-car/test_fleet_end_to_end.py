"""Real-module integration tests for the offline fleet CSV -> receipts -> verifier workflow.

Run from repository root: python3 -m unittest discover -s privi-car -p 'test_fleet_end_to_end.py' -v
No vehicle, chain, network, or payment involved.
"""
import copy
import csv
import io
import unittest

from fleet_batch import process_rows
from verify_fleet_export import verify_export


def csv_rows(body):
    return list(csv.DictReader(io.StringIO(body)))


class FleetEndToEndTests(unittest.TestCase):
    def test_opt_in_export_verifies_and_opt_out_is_rejected(self):
        rows = csv_rows(
            "vehicle_id,odometer_km,consent\n"
            "demo-truck-01,12000,yes\n"
            "demo-truck-02,25000,no\n"
            "demo-truck-03,30000,YES\n"
        )
        export = process_rows(rows)
        self.assertEqual(export["accepted"], 2)
        self.assertEqual(len(export["rejected"]), 1)
        self.assertEqual(export["rejected"][0]["line"], 3)
        self.assertTrue(verify_export(export)[0])

    def test_modified_mileage_is_detected(self):
        export = process_rows(csv_rows("vehicle_id,odometer_km,consent\ndemo-van,200,yes\n"))
        self.assertTrue(verify_export(export)[0])
        changed = copy.deepcopy(export)
        changed["receipts"][0]["event"]["odometer_km"] = 999
        self.assertFalse(verify_export(changed)[0])

    def test_invalid_rows_do_not_generate_receipts(self):
        export = process_rows(csv_rows(
            "vehicle_id,odometer_km,consent\n"
            "VIN-123,500,yes\n"
            "demo-van,-1,yes\n"
            "demo-van,not-a-number,yes\n"
        ))
        self.assertEqual(export["accepted"], 0)
        self.assertEqual(len(export["rejected"]), 3)
        self.assertTrue(verify_export(export)[0])

    def test_unexpected_csv_columns_rejected(self):
        with self.assertRaises(ValueError):
            process_rows(csv_rows(
                "vehicle_id,odometer_km,consent,driver_name\n"
                "demo-van,100,yes,Jane\n"
            ))


if __name__ == "__main__":
    unittest.main()
