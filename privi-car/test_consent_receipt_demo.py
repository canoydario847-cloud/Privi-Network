"""Run: python3 -m unittest discover -s privi-car -p 'test_*.py'"""
import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("receipt", pathlib.Path(__file__).with_name("consent_receipt_demo.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ConsentReceiptTests(unittest.TestCase):
    def test_denies_without_consent(self):
        with self.assertRaises(PermissionError):
            module.make_receipt("demo-1", 100, False)

    def test_receipt_is_local_and_pseudonymous(self):
        result = module.make_receipt("demo-1", 100, True)
        self.assertEqual(result["event"]["mode"], "LOCAL_DEMO_NOT_ON_CHAIN")
        self.assertNotIn("demo-1", str(result))
        self.assertEqual(len(result["sha256"]), 64)

    def test_invalid_odometer(self):
        with self.assertRaises(ValueError):
            module.make_receipt("demo-1", -1, True)

if __name__ == "__main__":
    unittest.main()
