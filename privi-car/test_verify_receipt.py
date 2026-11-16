"""Tests for the offline Privi Car receipt verifier.

Run: python3 -m unittest discover -s privi-car -p 'test_*.py'
"""
import copy
import hashlib
import json
import importlib.util
import pathlib
import unittest

folder = pathlib.Path(__file__).parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, folder / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


receipt_demo = load("consent_receipt_demo")
verifier = load("verify_receipt")


class VerifyReceiptTests(unittest.TestCase):
    def test_valid_receipt(self):
        receipt = receipt_demo.make_receipt("fleet-demo-7", 12345, True)
        self.assertTrue(verifier.verify_receipt(receipt)[0])

    def test_tampered_odometer(self):
        receipt = receipt_demo.make_receipt("fleet-demo-7", 12345, True)
        receipt["event"]["odometer_km"] = 99999
        self.assertFalse(verifier.verify_receipt(receipt)[0])

    def test_missing_consent(self):
        receipt = receipt_demo.make_receipt("fleet-demo-7", 12345, True)
        receipt["event"]["consent"]["granted"] = False
        self.assertFalse(verifier.verify_receipt(receipt)[0])

    def test_extra_field(self):
        receipt = receipt_demo.make_receipt("fleet-demo-7", 12345, True)
        receipt["event"]["driver_name"] = "do-not-collect"
        self.assertFalse(verifier.verify_receipt(receipt)[0])

    def test_malformed_timestamps_rejected_even_with_recomputed_hash(self):
        for timestamp in ("not-a-date", "2026-11-16T12:00:00",
                          "2026-13-16T12:00:00+00:00", "", "a" * 100):
            with self.subTest(timestamp=timestamp):
                receipt = receipt_demo.make_receipt("fleet-demo-7", 12345, True)
                receipt["event"]["recorded_at"] = timestamp
                canonical = json.dumps(receipt["event"], sort_keys=True,
                                       separators=(",", ":"), ensure_ascii=True)
                receipt["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
                self.assertFalse(verifier.verify_receipt(receipt)[0])

    def test_non_hex_hash_rejected(self):
        receipt = receipt_demo.make_receipt("fleet-demo-7", 12345, True)
        receipt["sha256"] = "z" * 64
        self.assertFalse(verifier.verify_receipt(receipt)[0])

    def test_valid_timezone_aware_receipt(self):
        receipt = receipt_demo.make_receipt("fleet-demo-7", 12345, True)
        self.assertTrue(verifier.verify_receipt(receipt)[0])

    def test_malformed_receipt(self):
        self.assertFalse(verifier.verify_receipt({"event": [], "sha256": ""})[0])


if __name__ == "__main__":
    unittest.main()
