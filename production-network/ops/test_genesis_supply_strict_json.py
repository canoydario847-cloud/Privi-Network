"""Reject non-RFC-8259 numeric constants in candidate genesis JSON."""
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from genesis_supply_audit import load_candidate_genesis

class StrictJsonTests(unittest.TestCase):
    def parse(self, data):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "genesis.json"
            path.write_text(data, encoding="utf-8")
            return load_candidate_genesis(path)

    def test_rejects_nan(self):
        with self.assertRaisesRegex(ValueError, "numeric constant"):
            self.parse('{"app_state":{"extra":NaN}}')

    def test_rejects_infinities(self):
        for value in ("Infinity", "-Infinity"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "numeric constant"):
                self.parse('{"app_state":{"extra":' + value + '}}')

    def test_valid_json_number_in_unrelated_field(self):
        self.assertEqual(self.parse('{"version":1}')["version"], 1)

if __name__ == "__main__":
    unittest.main()
