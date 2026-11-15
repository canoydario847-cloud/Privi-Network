"""Reject duplicate genesis JSON fields, including nested bank supply fields."""
import json
import unittest
from genesis_supply_audit import no_duplicate_keys

class DuplicateGenesisTests(unittest.TestCase):
    def test_top_level_duplicate(self):
        with self.assertRaisesRegex(ValueError, "duplicate genesis JSON key"):
            json.loads('{"chain_id":"a","chain_id":"b"}', object_pairs_hook=no_duplicate_keys)

    def test_nested_duplicate_amount(self):
        with self.assertRaisesRegex(ValueError, "duplicate genesis JSON key"):
            json.loads('{"bank":{"amount":"1","amount":"999"}}', object_pairs_hook=no_duplicate_keys)

    def test_unique_fields(self):
        obj=json.loads('{"bank":{"amount":"1"}}', object_pairs_hook=no_duplicate_keys)
        self.assertEqual(obj["bank"]["amount"], "1")

if __name__ == "__main__":
    unittest.main()
