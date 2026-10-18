"""Mock tests: public-testnet verifier must fail closed without using real networks."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "public_testnet_acceptance", Path(__file__).with_name("public_testnet_acceptance.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def sample():
    return {
        "network_type": "public_testnet",
        "valueless_asset": True, "asset_symbol": "TEST",
        "bnb_priv_separate": True, "financial_mainnet_live": False,
        "cosmos_chain_id": "privi-public-test-review-1", "evm_chain_id": 928271,
        "genesis_sha256": "a" * 64, "binary_sha256": "b" * 64,
        "operators": [
            {"operator_id": "operator%d" % i,
             "consensus_address": ("%040x" % (i + 1)),
             "fault_domain": "domain%d" % i,
             "independence_attestation_url": "https://proof%d.example.org/attestation" % i,
             "operator_controls_keys": True}
            for i in range(4)
        ],
        "comet_rpc": ["https://comet%d.example.org" % i for i in range(4)],
        "evm_rpc": ["https://evm%d.example.org" % i for i in range(2)]
    }

class MockRPC:
    values = {}
    def __init__(self, url):
        self.url = url
    def call(self, method, params=None):
        if method == "eth_chainId":
            return self.values.get((self.url, method), hex(928271))
        if method == "eth_blockNumber":
            return self.values.get((self.url, method), "0xa")
        if method == "eth_getBlockByNumber":
            return self.values.get((self.url, method), {"hash": "0x" + "f"*64})
        raise ValueError("unexpected method")

class PublicTestnetAcceptanceTests(unittest.TestCase):
    def test_valid_manifest_metadata(self):
        self.assertEqual(mod.validate_manifest(sample()), [])
    def test_dev_demo_identity_rejected(self):
        m=sample();m["cosmos_chain_id"]="local-4221";m["evm_chain_id"]=262144
        self.assertTrue(any("non-local" in e for e in mod.validate_manifest(m)))
        self.assertTrue(any("non-reference" in e for e in mod.validate_manifest(m)))
    def test_duplicate_operator_rejected(self):
        m=sample();m["operators"][1]["consensus_address"]=m["operators"][0]["consensus_address"]
        self.assertTrue(any("unique" in e for e in mod.validate_manifest(m)))
    def test_duplicate_gateway_host_rejected(self):
        m=sample();m["evm_rpc"][1]="https://evm0.example.org/other/path"
        self.assertTrue(any("unique" in e for e in mod.validate_manifest(m)))
    def test_private_keys_forbidden(self):
        m=sample();m["operators"][0]["private_key"]="never-put-in-repo"
        self.assertTrue(any("secret" in e for e in mod.validate_manifest(m)))
    def test_unencrypted_rpc_rejected(self):
        m=sample();m["evm_rpc"][0]="http://evm0.example.org"
        self.assertTrue(any("HTTPS" in e for e in mod.validate_manifest(m)))
    def test_false_attestation_rejected(self):
        m=sample();m["operators"][0]["operator_controls_keys"]=False
        self.assertTrue(any("key custody" in e for e in mod.validate_manifest(m)))
    def test_initial_genesis_hash_and_chain_identity(self):
        m=sample()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"genesis.json"
            path.write_text(json.dumps({"chain_id":m["cosmos_chain_id"]}))
            m["genesis_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(mod.check_genesis(path,m),m["genesis_sha256"])
            m["genesis_sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"SHA-256"):
                mod.check_genesis(path,m)
    def test_gateway_cross_hash_pass(self):
        MockRPC.values={}
        out=mod.audit_evm_gateways(sample()["evm_rpc"],928271,MockRPC)
        self.assertEqual(out["common_block"],9)
    def test_gateway_chain_mismatch(self):
        MockRPC.values={("https://evm0.example.org","eth_chainId"):hex(4221)}
        with self.assertRaisesRegex(ValueError,"chain mismatch"):
            mod.audit_evm_gateways(sample()["evm_rpc"],928271,MockRPC)
        MockRPC.values={}
    def test_gateway_history_disagreement(self):
        MockRPC.values={("https://evm0.example.org","eth_getBlockByNumber"):{"hash":"0x"+"e"*64}}
        with self.assertRaisesRegex(ValueError,"hashes disagree"):
            mod.audit_evm_gateways(sample()["evm_rpc"],928271,MockRPC)
        MockRPC.values={}
    def test_live_operator_addresses_present(self):
        m=sample()
        fake_consensus=lambda endpoints,expected: {
            "blockHeight":10,"cosmosChainId":expected,"votingValidators":4}
        fake_valset=lambda endpoint,height: {
            o["consensus_address"].upper():10 for o in m["operators"]}
        outcome=mod.audit_network(
            m,consensus_probe=fake_consensus,validator_probe=fake_valset,
            evm_probe=lambda endpoints,expect_chain: {"chain_id":expect_chain})
        self.assertEqual(outcome["verified_operator_address_count"],4)
    def test_missing_live_validator_rejected(self):
        m=sample()
        with self.assertRaisesRegex(ValueError,"absent"):
            mod.audit_network(
                m,
                consensus_probe=lambda endpoints,expected: {"blockHeight":9},
                validator_probe=lambda endpoint,height: {},
                evm_probe=lambda endpoints,expected: {})

if __name__=="__main__":
    unittest.main()
