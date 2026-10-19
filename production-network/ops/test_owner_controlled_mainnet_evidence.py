"""Offline-only PRVI evidence regression tests for 1-owner / 4-host network.

These are synthetic, never actual production keys, attestations, coins or
genesis. All financial mainnet launch evidence remains NO-GO.
"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from verify_mainnet_evidence import assess

def fixture():
    genesis={
        "chain_id": "privi-candidate-review-not-live-1",
        "app_state":{
            "bank":{
                "balances":[{"address":"privi1syntheticfixture","coins":[
                    {"denom":"aprvi","amount":"3000000000000000000"}]}],
                "supply":[{"denom":"aprvi","amount":"3000000000000000000"}],
                "denom_metadata":[{
                    "base":"aprvi","display":"PRVI","symbol":"PRVI",
                    "denom_units":[{"denom":"aprvi","exponent":0},{"denom":"PRVI","exponent":18}]
                }]
            },
            "evm":{"params":{"evm_denom":"aprvi"}},
            "staking":{"params":{"bond_denom":"aprvi"}},
            "erc20":{"params":{"permissionless_registration":False},"token_pairs":[]},
            "mint":{
                "params":{"mint_denom":"aprvi","inflation_rate_change":"0.000000000000000000",
                          "inflation_min":"0.000000000000000000","inflation_max":"0.000000000000000000"},
                "minter":{"inflation":"0.000000000000000000",
                          "annual_provisions":"0.000000000000000000"}
            }
        }
    }
    manifest={
        "network":"privi-mainnet", "symbol":"PRVI",
        "test_assets_separate":True,"bnb_priv_separate":True,
        "max_supply_whole_prvi":1_000_000_000,
        "cosmos_chain_id":genesis["chain_id"],"evm_chain_id":999999,
        "base_denom":"aprvi", "operator":"Privi World Corp",
        "governance_model":"single-operator-permissioned",
        "independent_operator_count":1,
        "validators":[
            {"id":f"privi-owner-val-{i:02d}", "operator":"Privi World Corp",
             "host_id":f"ci-fake-host-{i}", "fault_domain":f"ci-fake-domain-{i}",
             "consensus_pubkey_sha256":f"{i:064x}",
             "signer_attestation":f"CI_TEST_ONLY_NOT_VERIFIED_{i}",
             "voting_power_percent":25}
            for i in range(1,5)
        ],
    }
    return manifest,genesis

def check(t, mutate=None):
    with tempfile.TemporaryDirectory() as temporary:
        m,g=fixture()
        if mutate is not None:
            mutate(m,g)
        filename=Path(temporary)/"unsigned-test-fixture.json"
        filename.write_text(json.dumps(g,sort_keys=True),encoding="utf-8")
        m["genesis_sha256"]=hashlib.sha256(filename.read_bytes()).hexdigest()
        return assess(m,filename)

class OwnerControlledEvidenceTests(unittest.TestCase):
    def test_four_distinct_hosts_same_owner_is_correctly_identified(self):
        problems=check(self)
        self.assertFalse([p for p in problems if ("validator" in p or "operator" in p) and "externally verified" not in p],
                         problems)
        self.assertFalse([p for p in problems if "genesis parameter audit" in p or
                          "bank supply audit" in p],problems)
        self.assertTrue(any("externally verified" in p for p in problems))
    def test_refuses_claim_of_four_independent_operators(self):
        problems=check(self,lambda m,g:m.update(independent_operator_count=4))
        self.assertTrue(any("independent_operator_count" in p for p in problems))
    def test_requires_correct_operator(self):
        problems=check(self,lambda m,g:m["validators"][2].update(operator="separate-company"))
        self.assertTrue(any("validator[2] operator" in p for p in problems))
    def test_duplicate_host_refused(self):
        def edit(m,g):m["validators"][1]["host_id"]=m["validators"][0]["host_id"]
        self.assertTrue(any("distinct validator host_id" in p for p in check(self,edit)))
    def test_duplicate_key_refused(self):
        def edit(m,g):
            m["validators"][2]["consensus_pubkey_sha256"]=m["validators"][0]["consensus_pubkey_sha256"]
        self.assertTrue(any("distinct validator consensus_pubkey_sha256" in p
                            for p in check(self,edit)))
    def test_missing_signer_attestation_refused(self):
        def edit(m,g):m["validators"][0]["signer_attestation"]="UNASSIGNED"
        self.assertTrue(any("signer attestation" in p for p in check(self,edit)))
    def test_wrong_vote_power_refused(self):
        def edit(m,g):m["validators"][0]["voting_power_percent"]=50
        self.assertTrue(any("voting power" in p for p in check(self,edit)))
    def test_wrong_validator_count_refused(self):
        def edit(m,g):m["validators"].pop()
        self.assertTrue(any("exactly four" in p for p in check(self,edit)))
    def test_staking_cannot_use_upstream_stake(self):
        def edit(m,g):g["app_state"]["staking"]["params"]["bond_denom"]="stake"
        self.assertTrue(any("native PRVI genesis parameter audit" in p
                            for p in check(self,edit)))
    def test_mint_cannot_be_inflationary(self):
        def edit(m,g):g["app_state"]["mint"]["minter"]["inflation"]="0.0100"
        self.assertTrue(any("native PRVI genesis parameter audit" in p
                            for p in check(self,edit)))
    def test_erc20_permissionless_defaults_are_unsafe(self):
        def edit(m,g):
            g["app_state"]["erc20"]["params"]["permissionless_registration"]=True
        self.assertTrue(any("ERC20 permissionless registration" in p
                            for p in check(self,edit)))

    def test_native_aprvi_erc20_mapping_is_blocked(self):
        def edit(m,g):
            g["app_state"]["erc20"]["token_pairs"]=[
                {"denom":"aprvi","enabled":False}]
        self.assertTrue(any("native aprvi" in p
                            for p in check(self,edit)))

    def test_bad_metadata_precision_refused(self):
        def edit(m,g):
            g["app_state"]["bank"]["denom_metadata"][0]["denom_units"][1]["exponent"]=6
        self.assertTrue(any("native PRVI genesis parameter audit" in p
                            for p in check(self,edit)))
    def test_manifest_nonobject_fails(self):
        self.assertTrue(any("manifest must be" in p for p in assess(None,Path("/missing"))))

if __name__=="__main__":
    unittest.main()
