"""Offline regression tests for the Privi launch evidence gate."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("gate", Path(__file__).with_name("mainnet_evidence_gate.py"))
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

class GateTests(unittest.TestCase):
    def test_missing_evidence_fails_closed(self):
        self.assertTrue(gate.check({}))
    def test_demo_chain_rejected(self):
        data = {key: "reviewed" for key in gate.REQUIRED}
        data.update(network="privi-financial-mainnet", evm_chain_id="262144",
                    test_asset_valueless=True, bnb_priv_separate=True,
                    production_mint_enabled=False,
                    audited_binary_sha256="a"*64, signed_genesis_sha256="b"*64)
        self.assertTrue(any("demo" in e for e in gate.check(data)))
    def test_complete_fields_only_means_evidence_ready(self):
        data = {key: "reviewed" for key in gate.REQUIRED}
        data.update(network="privi-financial-mainnet", evm_chain_id="987654",
                    test_asset_valueless=True, bnb_priv_separate=True,
                    production_mint_enabled=False,
                    audited_binary_sha256="a"*64, signed_genesis_sha256="b"*64)
        self.assertEqual(gate.check(data), [])

if __name__ == "__main__":
    unittest.main()
