#!/usr/bin/env python3
"""Negative tests for actual consensus/SDK genesis public-key consistency.

These are dummy public keys and mock signature SHAPES only. This test suite
does not create keys, submit transactions or claim signatures are verified.
"""
import base64
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("privi_operator_binding", HERE / "genesis_operator_binding.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def roster(count=7):
    return {"operators": [
        {"operator_id": f"synthetic-{i}", "consensus_pubkey": (bytes([i+1]) * 32).hex(), "voting_power": 1}
        for i in range(count)
    ]}


def comet_genesis(r):
    return {"chain_id": "privi-reviewed-nonproduction-1", "app_state": {"genutil": {"gen_txs": []}},
            "validators": [
                {"pub_key": {"type": "tendermint/PubKeyEd25519",
                             "value": base64.b64encode(bytes.fromhex(row["consensus_pubkey"])).decode()},
                 "power": str(row["voting_power"])}
                for row in r["operators"]
            ]}


def gentx_genesis(r):
    out = {"chain_id": "privi-reviewed-nonproduction-1", "validators": [],
           "app_state": {"genutil": {"gen_txs": []}}}
    for i, row in enumerate(r["operators"]):
        out["app_state"]["genutil"]["gen_txs"].append({
            "body": {"messages": [{
                "@type": "/cosmos.staking.v1beta1.MsgCreateValidator",
                "pubkey": {"@type": "/cosmos.crypto.ed25519.PubKey",
                           "key": base64.b64encode(bytes.fromhex(row["consensus_pubkey"])).decode()},
                "validator_address": "privivaloper1" + str(i)*38,
                "value": {"denom": "aprvi", "amount": "1000000000000000000"}
            }]},
            "auth_info": {"signer_infos": [{"sequence": "0"}]},
            "signatures": [base64.b64encode(bytes([i+2])*64).decode()]
        })
    return out


class GenesisOperatorBindingTests(unittest.TestCase):
    def test_comet_and_gentx_paths_match_unique_roster(self):
        r = roster()
        self.assertEqual(m.validate_binding(comet_genesis(r), r), [])
        self.assertEqual(m.validate_binding(gentx_genesis(r), r), [])
        both = gentx_genesis(r)
        both["validators"] = comet_genesis(r)["validators"]
        self.assertEqual(m.validate_binding(both, r), [])

    def test_missing_genesis_public_operators_fails(self):
        r = roster()
        doc = {"app_state": {"genutil": {"gen_txs": []}}, "validators": []}
        errors = m.validate_binding(doc, r)
        self.assertTrue(any("No Comet genesis validators" in x for x in errors), errors)

    def test_stolen_or_duplicate_key_fails(self):
        r = roster()
        doc = comet_genesis(r)
        doc["validators"][0]["pub_key"] = doc["validators"][1]["pub_key"]
        errors = m.validate_binding(doc, r)
        self.assertTrue(any("duplicate consensus key" in x for x in errors), errors)

    def test_roster_key_substitution_fails(self):
        r = roster()
        doc = comet_genesis(r)
        r["operators"][0]["consensus_pubkey"] = (bytes([200])*32).hex()
        self.assertTrue(any("keyset" in x for x in m.validate_binding(doc, r)))

    def test_comet_power_tampering_fails(self):
        r = roster()
        doc = comet_genesis(r)
        doc["validators"][0]["power"] = "2"
        self.assertTrue(any("voting power differs" in x for x in m.validate_binding(doc, r)))

    def test_subcritical_operator_power_rule_fails(self):
        r = roster()
        r["operators"][0]["voting_power"] = 4
        doc = comet_genesis(r)
        self.assertTrue(any("one third" in x for x in m.validate_binding(doc, r)))

    def test_gentx_needs_staking_denom_and_signed_body(self):
        r = roster()
        doc = gentx_genesis(r)
        doc["app_state"]["genutil"]["gen_txs"][0]["body"]["messages"][0]["value"]["denom"] = "atest"
        self.assertTrue(any("aprvi" in x for x in m.validate_binding(doc, r)))
        doc = gentx_genesis(r)
        doc["app_state"]["genutil"]["gen_txs"][0]["signatures"] = []
        self.assertTrue(any("not signed" in x for x in m.validate_binding(doc, r)))

    def test_duplicate_gentx_consensus_key_fails(self):
        r = roster()
        doc = gentx_genesis(r)
        first = doc["app_state"]["genutil"]["gen_txs"][0]["body"]["messages"][0]
        second = doc["app_state"]["genutil"]["gen_txs"][1]["body"]["messages"][0]
        second["pubkey"] = first["pubkey"]
        self.assertTrue(any("duplicate consensus key" in x for x in m.validate_binding(doc, r)))

    def test_non_ed25519_consensus_keys_fail(self):
        r = roster()
        doc = comet_genesis(r)
        doc["validators"][0]["pub_key"]["type"] = "tendermint/PubKeySecp256k1"
        self.assertTrue(any("Ed25519" in x for x in m.validate_binding(doc, r)))

    def test_missing_roster_and_invalid_genesis_fail(self):
        self.assertTrue(m.validate_binding({}, {"operators": []}))
        self.assertTrue(m.validate_binding({"validators": []}, roster()))

    def test_reject_int64_unsafe_amounts(self):
        for raw in ("0", "-1", "1.0", "001", float("nan"), "9"*100):
            with self.assertRaises(ValueError):
                m.canonical_integer(raw)


if __name__ == "__main__":
    unittest.main()
