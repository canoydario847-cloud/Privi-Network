#!/usr/bin/env python3
"""Read-only tests for mainnet's fail-closed launch blockers."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("preflight", HERE / "mainnet_preflight.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MainnetPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = json.loads((HERE / "manifest.example.json").read_text())

    def test_template_must_not_pass(self):
        errors = m.check_manifest(copy.deepcopy(self.template))
        self.assertGreater(len(errors), 10)
        self.assertTrue(any("seven" in e for e in errors))
        self.assertTrue(any("release gate" in e for e in errors))

    def test_development_ids_are_blocked(self):
        doc = copy.deepcopy(self.template)
        doc["network"]["cosmos_chain_id"] = "local-4221"
        doc["network"]["evm_chain_id"] = 262144
        errors = m.check_manifest(doc)
        self.assertTrue(any("Cosmos chain" in e for e in errors))
        self.assertTrue(any("EVM numeric" in e for e in errors))

    def test_token_supply_cannot_be_changed(self):
        doc = copy.deepcopy(self.template)
        doc["asset"]["max_supply"] = "10000000000"
        doc["asset"]["inflation_enabled"] = True
        doc["distribution"]["total_allocations_base_units"] = str(10**28)
        errors = m.check_manifest(doc)
        self.assertTrue(any("cap must" in e for e in errors))
        self.assertTrue(any("inflation" in e for e in errors))
        self.assertTrue(any("10^27" in e for e in errors))

    def test_unreviewed_evidence_fails(self):
        doc = copy.deepcopy(self.template)
        doc["distribution"]["public_vesting_schedule_url"] = "http://fake.example"
        errors = m.check_manifest(doc)
        self.assertTrue(any("public_vesting_schedule_url" in e for e in errors))

    def test_no_signature_approval_by_script(self):
        self.assertIn("independent audits", m.__doc__.lower())


if __name__ == "__main__":
    unittest.main()
