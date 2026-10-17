"""Fail-closed tests for launch evidence checker (no real mainnet involved)."""
import importlib.util
import json
import hashlib
import tempfile
import unittest
from pathlib import Path

module_path = Path(__file__).with_name("verify_mainnet_evidence.py")
spec = importlib.util.spec_from_file_location("verify_mainnet_evidence", module_path)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

class MainnetEvidenceTest(unittest.TestCase):
    def test_missing_genesis_fails(self):
        problems = checker.assess({}, Path("/this/does/not/exist/privi-genesis.json"))
        self.assertTrue(any("genesis file missing" in p for p in problems))

    def test_demo_network_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "genesis.json"
            path.write_text(json.dumps({"chain_id": "local-4221"}))
            problems = checker.assess({
                "network": "privi-mainnet", "symbol": "PRVI",
                "test_assets_separate": True, "bnb_priv_separate": True,
                "max_supply_whole_prvi": 1_000_000_000,
                "cosmos_chain_id": "local-4221", "evm_chain_id": 4221,
                "base_denom": "aprvi", "validators": []
            }, path)
            self.assertTrue(any("Cosmos chain ID" in p for p in problems))
            self.assertTrue(any("EVM chain ID" in p for p in problems))
            self.assertTrue(any("four validators" in p for p in problems))

    def test_false_cap_is_rejected(self):
        problems = checker.assess({"max_supply_whole_prvi": True}, Path("/missing"))
        self.assertTrue(any("max supply" in p for p in problems))

    def test_initial_genesis_supply_exceeds_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "genesis.json"
            huge = str(1_000_000_000 * 10**18 + 1)
            path.write_text(json.dumps({
                "chain_id": "privi-candidate-1",
                "app_state": {"bank": {
                    "balances": [{"address": "privi1example", "coins": [{"denom": "aprvi", "amount": huge}]}],
                    "supply": [{"denom": "aprvi", "amount": huge}]
                }}
            }))
            manifest = {
                "network": "privi-mainnet", "symbol": "PRVI", "test_assets_separate": True,
                "bnb_priv_separate": True, "max_supply_whole_prvi": 1000000000,
                "cosmos_chain_id": "privi-candidate-1", "evm_chain_id": 999999,
                "base_denom": "aprvi", "genesis_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "validators": [
                    {"operator_id": "op%d" % i, "consensus_pubkey": "pub%d" % i,
                     "fault_domain": "domain%d" % i, "independent_operator_attestation": True}
                    for i in range(4)
                ]
            }
            problems = checker.assess(manifest, path)
            self.assertTrue(any("initial PRVI bank supply audit" in p and "exceeds" in p for p in problems))

if __name__ == "__main__":
    unittest.main()
