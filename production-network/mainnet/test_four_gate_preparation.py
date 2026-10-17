#!/usr/bin/env python3
"""Negative/unit tests — all fixtures are synthetic and financially valueless."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ids = load("network_id_check.py", "id_review")
vesting = load("vesting_plan.py", "vesting_review")
operators = load("independent_operator_roster.py", "operator_review")
rehearsal = load("rehearsal_audit.py", "rehearsal_review")


def ledger():
    return {"allocations": [
        {"category": k, "address": "privi1" + "q" * 37 + chr(ord("a") + i),
         "amount_base_units": str(v),
         **({"schedule": "contributor_12_plus_36_months" if k == "contributors"
             else "monthly_36_months"} if k in vesting.SENSITIVE else {})}
        for i, (k, v) in enumerate(vesting.BUCKETS.items())
    ]}


def valid_roster():
    out = {"status": "PROPOSED_EXTERNAL_OPERATOR_ROSTER",
           "independent_ownership_review_complete": True,
           "independent_ownership_review_url": "https://review.example.org/owners",
           "operators": []}
    for i in range(7):
        out["operators"].append({
            "operator_id": f"synthetic-op-{i}",
            "legal_controller_id": f"synthetic-legal-{i}",
            "signing_key_custodian_id": f"synthetic-keyowner-{i}",
            "cloud_account_owner_id": f"synthetic-cloud-{i}",
            "consensus_pubkey": f"{i + 1:064x}",
            "infrastructure_provider": f"provider-{i%3}",
            "failure_region": f"region-{i%3}",
            "voting_power": 1,
            "operator_independence_evidence_url": "https://review.example.org/independence",
            "custody_review_url": "https://review.example.org/custody",
            "backup_rehearsal_url": "https://review.example.org/recovery",
            "signed_genesis_attestation_url": "https://review.example.org/genesis",
            "oncall_runbook_url": "https://review.example.org/oncall",
            "keys_exclusively_operator_controlled": True,
            "independent_human_identity_reviewed": True,
            "signed_genesis_attestation_crypto_verified": True,
            "double_sign_fencing_rehearsed": True,
        })
    return out


class MainnetFourGatesTests(unittest.TestCase):
    def test_design_id_candidate_is_unreserved(self):
        doc = json.loads((HERE / "candidate_network_ids.json").read_text())
        self.assertEqual(doc["status"], "PROPOSED_UNRESERVED_NOT_FOR_GENESIS")
        self.assertEqual(ids.check(doc, [{"chainId": 99}], [{"chain_id": "other-1"}]), [])

    def test_id_collisions_fail(self):
        doc = json.loads((HERE / "candidate_network_ids.json").read_text())
        collisions = ids.check(doc, [{"chainId": doc["evm_chain_id"]}],
                               [{"chain_id": doc["cosmos_chain_id"]}])
        self.assertTrue(any("EVM chain ID collision" in x for x in collisions))
        self.assertTrue(any("Cosmos chain ID collision" in x for x in collisions))
        self.assertTrue(ids.check(doc, [], []))

    def test_supply_ledger_exact_cap_and_vesting_schedule(self):
        output = vesting.plan(ledger(), 1893456000)
        self.assertEqual(output["status"], "DRAFT_ACCOUNTS_FOR_REVIEW_NOT_GENESIS")
        self.assertEqual(len(output["vesting_accounts"]), 3)
        self.assertEqual(sum(int(x) for x in output["allocation_categories"].values()), 10**27)
        for row in output["vesting_accounts"]:
            account = row["account"]
            schedule = account["vesting_periods"]
            self.assertEqual(len(schedule), 36)
            self.assertEqual(sum(int(x["amount"][0]["amount"]) for x in schedule),
                             int(account["base_vesting_account"]["original_vesting"][0]["amount"]))
            self.assertEqual(sum(int(x["length"]) for x in schedule),
                             int(account["base_vesting_account"]["end_time"]) -
                             int(account["start_time"]))
        contributor = next(x for x in output["vesting_accounts"]
                           if x["category"] == "contributors")
        self.assertGreater(int(contributor["account"]["vesting_periods"][0]["length"]), 365*24*3600)

    def test_missing_recipient_and_unbalanced_supply_fail(self):
        data = ledger()
        data["allocations"].pop()
        with self.assertRaises(ValueError):
            vesting.plan(data, 1893456000)
        data = ledger()
        data["allocations"][1]["address"] = data["allocations"][0]["address"]
        with self.assertRaises(ValueError):
            vesting.plan(data, 1893456000)

    def test_operator_template_does_not_pass(self):
        template = json.loads((HERE / "operator_roster.template.json").read_text())
        self.assertTrue(operators.screen(template))
        self.assertEqual(operators.screen(valid_roster()), [])

    def test_duplicate_owner_and_missing_evidence_fail(self):
        doc = valid_roster()
        doc["operators"][1]["legal_controller_id"] = doc["operators"][0]["legal_controller_id"]
        doc["operators"][2]["signed_genesis_attestation_url"] = ""
        errs = operators.screen(doc)
        self.assertTrue(any("duplicated legal_controller_id" in s for s in errs))
        self.assertTrue(any("signed_genesis_attestation_url" in s for s in errs))

    def test_rehearsal_requires_all_seven_signatures(self):
        urls = [f"http://private-{i}:26657" for i in range(7)]
        voters = {f"{i:040X}":1 for i in range(1, 8)}
        outcome = {"nodes": 7, "votingValidators": 7, "blockHeight": 10,
                   "signedVotingPower": 7, "totalVotingPower": 7,
                   "cosmosChainId": "privi-review-1", "blockHash": "A"*64}
        sigs = [{"validator_address": key, "block_id_flag": 2, "signature": "not-cryptographic-proof"}
                for key in voters]
        with patch.object(rehearsal, "audit", return_value=outcome), \
             patch.object(rehearsal, "validator_set", return_value=voters), \
             patch.object(rehearsal, "get", return_value={"signed_header": {"commit": {"signatures": sigs}}}), \
             patch.object(rehearsal, "check_evm", return_value={"chainId": 100001, "blockHeight": 10}):
            result = rehearsal.proof(urls, "privi-review-1", "http://private-evm:8545", 100001)
            self.assertTrue(result["all_seven_commit_signatures_present"])
            with patch.object(rehearsal, "get", return_value={
                "signed_header": {"commit": {"signatures": sigs[:-1]}}}):
                with self.assertRaisesRegex(ValueError, "All seven"):
                    rehearsal.proof(urls, "privi-review-1", "http://private-evm:8545", 100001)
        with self.assertRaises(ValueError):
            rehearsal.proof(urls, "local-privi-seven-4221", "http://private-evm:8545", 262144)


if __name__ == "__main__":
    unittest.main()
