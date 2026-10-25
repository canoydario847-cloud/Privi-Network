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

    def test_upstream_dev_evm_identity_cannot_be_mainnet(self):
        base = {
            "network": "privi-mainnet", "symbol": "PRVI",
            "test_assets_separate": True, "bnb_priv_separate": True,
            "max_supply_whole_prvi": 1_000_000_000,
            "cosmos_chain_id": "privi-candidate-1", "base_denom": "aprvi",
        }
        for demo_chain_id in (262144, 4221, 1337, 31337, 56, 1, 97):
            manifest = dict(base, evm_chain_id=demo_chain_id)
            problems = checker.assess(manifest, Path("/definitely/missing-genesis.json"))
            self.assertTrue(any("EVM chain ID" in p for p in problems),
                            "dev/public chain id should be rejected: %d" % demo_chain_id)

    def test_developer_fee_denom_cannot_be_proposed_financial_prvi(self):
        base = {
            "network": "privi-mainnet", "symbol": "PRVI",
            "test_assets_separate": True, "bnb_priv_separate": True,
            "max_supply_whole_prvi": 1_000_000_000,
            "cosmos_chain_id": "privi-candidate-1", "evm_chain_id": 424242,
        }
        for dev_denom in ("atest", "test", "stake", "aphotino"):
            manifest = dict(base, base_denom=dev_denom)
            problems = checker.assess(manifest, Path("/definitely/missing-genesis.json"))
            self.assertTrue(any("PRVI base denomination" in p for p in problems),
                            "developer denom should be rejected: %s" % dev_denom)

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

    def test_sha_matching_ambiguous_duplicate_genesis_still_rejected(self):
        # A correct SHA of ambiguous input is NOT valid genesis evidence:
        # alternate parsers might select a different bank object.
        raw = b'{"chain_id":"privi-candidate-1","app_state":{"bank":{},"bank":{}}}'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "genesis.json"
            path.write_bytes(raw)
            manifest = {
                "cosmos_chain_id": "privi-candidate-1",
                "base_denom": "aprvi",
                "genesis_sha256": hashlib.sha256(raw).hexdigest(),
            }
            problems = checker.assess(manifest, path)
            self.assertTrue(any("duplicate genesis JSON key" in p for p in problems), problems)
            self.assertTrue(any("genesis invalid or ambiguous" in p for p in problems), problems)

    def test_sha_matching_oversized_genesis_cannot_bypass_size_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "genesis.json"
            with path.open("wb") as stream:
                stream.seek(8_000_000)
                stream.write(b"x")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = {
                "cosmos_chain_id": "privi-candidate-1",
                "base_denom": "aprvi",
                "genesis_sha256": digest,
            }
            problems = checker.assess(manifest, path)
            self.assertTrue(any("8 MB" in p for p in problems), problems)

    def test_sha_matching_malformed_other_denom_is_rejected(self):
        raw = json.dumps({
            "chain_id": "privi-candidate-1",
            "app_state": {"bank": {
                "balances": [{"address": "privi1example",
                              "coins": [{"denom": "aprvi", "amount": "100"},
                                        {"denom": "uatom", "amount": "5"}]}],
                "supply": [{"denom": "aprvi", "amount": "100"},
                           {"denom": "uatom", "amount": "6"}],
            }},
        }).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "genesis.json"
            path.write_bytes(raw)
            manifest = {"cosmos_chain_id": "privi-candidate-1",
                        "base_denom": "aprvi",
                        "genesis_sha256": hashlib.sha256(raw).hexdigest()}
            problems = checker.assess(manifest, path)
            self.assertTrue(any("initial PRVI bank supply audit" in p and
                                "across denominations" in p for p in problems), problems)

if __name__ == "__main__":
    unittest.main()
