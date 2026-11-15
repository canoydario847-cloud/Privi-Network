"""Input safety regression tests for the read-only Privi genesis auditor."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
from genesis_supply_audit import load_candidate_genesis

class GenesisInputSafetyTests(unittest.TestCase):
    def test_oversized_file_rejected_before_read(self):
        candidate = Mock()
        candidate.stat.return_value.st_size = 64 * 1024 * 1024 + 1
        with self.assertRaisesRegex(ValueError, "64 MiB"):
            load_candidate_genesis(candidate)
        candidate.read_text.assert_not_called()

    def test_duplicate_nested_supply_key_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "genesis.json"
            path.write_text('{"app_state":{"bank":{"supply":[],"supply":[]}}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate genesis JSON key"):
                load_candidate_genesis(path)

    def test_bounded_unique_json_accepted_for_structural_review(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "genesis.json"
            path.write_text('{"chain_id":"privi-candidate-1"}', encoding="utf-8")
            self.assertEqual(load_candidate_genesis(path)["chain_id"], "privi-candidate-1")

if __name__ == "__main__":
    unittest.main()
