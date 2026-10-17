#!/usr/bin/env python3
"""Fail-closed, release-review-only Privi evidence inventory tests."""
import copy
from pathlib import Path
import sys
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from launch_evidence_inventory import (
    HERE, SAFE_STATUS, read_public_json, report, ceremony, operator_screen
)


class PriviLaunchEvidenceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.docs = {
            "config": read_public_json(HERE / "privi_chain_config.json"),
            "manifest": read_public_json(HERE / "manifest.example.json"),
            "roster": read_public_json(HERE / "operator_roster.template.json"),
            "release": read_public_json(HERE / "operator-kit/release.template.json"),
            "attestations": read_public_json(HERE / "operator-kit/attestations.template.json"),
        }

    def test_real_repository_templates_are_no_go(self):
        data = report(**self.docs)
        self.assertEqual(data["release_decision"], "NO_GO")
        self.assertEqual(data["status"], SAFE_STATUS)
        self.assertEqual(data["production_operator_count"], 0)
        self.assertEqual(data["cryptographically_verified_release_signature_count"], 0)
        self.assertFalse(data["manual_deployment_authorized_by_this_report"])
        self.assertFalse(data["audited_genesis_supplied"])
        self.assertEqual(len(data["gates"]), 6)
        self.assertTrue(all(x["status"] == "BLOCKED" for x in data["gates"]))

    def test_founder_approval_claim_and_boolean_flags_never_override(self):
        docs = copy.deepcopy(self.docs)
        docs["manifest"]["launch_authorization"] = {
            "genesis_ceremony_complete": True,
            "operators_verified": True,
            "critical_findings_remediated": True,
            "manual_release_gate_open": True,
        }
        docs["manifest"]["founder_approval"] = "all approved"
        result = report(**docs)
        self.assertEqual(result["release_decision"], "NO_GO")
        final = next(x for x in result["gates"] if x["key"] == "final_manual_authorization")
        self.assertEqual(final["status"], "BLOCKED")

    def test_missing_required_documents_fail_explicitly(self):
        docs = copy.deepcopy(self.docs)
        docs["roster"] = None
        with self.assertRaisesRegex(ValueError, "Five public evidence documents"):
            report(**docs)

    def test_chosen_chain_ids_with_unreviewed_config_still_blocked(self):
        docs = copy.deepcopy(self.docs)
        docs["config"]["network"]["cosmos_chain_id"] = "privi-production-unverified-1"
        docs["config"]["network"]["evm_chain_id"] = 998877
        result = report(**docs)
        self.assertEqual(result["gates"][0]["status"], "BLOCKED")

    def test_valid_7_synthetic_signatures_are_not_real_world_clearance(self):
        docs = copy.deepcopy(self.docs)
        release = {
            "cosmos_chain_id": "privi-production-review-only-1",
            "evm_chain_id": 998877,
            "canonical_genesis_sha256": "1"*64,
            "binary_sha256": "2"*64,
            "allocations_sha256": "3"*64,
        }
        docs["release"] = release
        docs["config"]["status"] = "AUDITED_MAINNET_RELEASE_CANDIDATE"
        docs["config"]["network"].update({
            "cosmos_chain_id": release["cosmos_chain_id"],
            "evm_chain_id": release["evm_chain_id"],
        })
        docs["manifest"]["network"].update({
            "cosmos_chain_id": release["cosmos_chain_id"],
            "evm_chain_id": release["evm_chain_id"],
        })
        roster = {
            "status": "PROPOSED_EXTERNAL_OPERATOR_ROSTER",
            "independent_ownership_review_complete": True,
            "independent_ownership_review_url": "https://independent-review.example.com/report",
            "operators": [],
        }
        items = []
        for idx in range(7):
            op = "synthetic-review-%02d" % idx
            # Disposable crypto keys prove signatures only, NOT operator
            # legal identity, key custody, live nodes or external reviews.
            consensus = bytes([idx+1])*32
            signer = Ed25519PrivateKey.generate()
            pub = signer.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            genesiskey = consensus.hex()
            roster["operators"].append({
                "operator_id": op,
                "legal_controller_id": "fake-owner-%02d" % idx,
                "signing_key_custodian_id": "fake-custodian-%02d" % idx,
                "cloud_account_owner_id": "fake-cloud-%02d" % idx,
                "consensus_pubkey": genesiskey,
                "infrastructure_provider": "fake-provider-%d" % (idx % 3),
                "failure_region": "fake-region-%d" % (idx % 3),
                "voting_power": 1,
                "operator_independence_evidence_url": "https://independent-review.example.com/ownership",
                "custody_review_url": "https://independent-review.example.com/custody",
                "backup_rehearsal_url": "https://independent-review.example.com/backup",
                "signed_genesis_attestation_url": "https://independent-review.example.com/attestation",
                "oncall_runbook_url": "https://independent-review.example.com/runbook",
                "keys_exclusively_operator_controlled": True,
                "independent_human_identity_reviewed": True,
                "signed_genesis_attestation_crypto_verified": True,
                "double_sign_fencing_rehearsed": True,
            })
            signed = signer.sign(ceremony.canonical_payload(release, op, genesiskey))
            items.append({
                "operator_id": op,
                "consensus_pubkey": genesiskey,
                "attestation_public_key": pub.hex(),
                "signature": signed.hex(),
            })
        self.assertEqual(operator_screen.screen(roster), [])
        docs["roster"] = roster
        docs["attestations"] = {"status": "PUBLIC_CRYPTO_SIGNATURES_TEST_ONLY",
                                "attestations": items}
        result = report(**docs)
        self.assertEqual(result["cryptographically_verified_release_signature_count"], 7)
        self.assertEqual(result["release_decision"], "NO_GO")
        self.assertFalse(result["manual_deployment_authorized_by_this_report"])
        self.assertEqual(
            next(g for g in result["gates"] if g["key"] == "final_manual_authorization")["status"],
            "BLOCKED")
        self.assertEqual(
            next(g for g in result["gates"] if g["key"] == "audited_allocations_and_genesis")["status"],
            "BLOCKED")
        # Tampering with one release signature must remove any verified count.
        docs["attestations"]["attestations"][0]["signature"] = "0"*128
        tampered = report(**docs)
        self.assertEqual(tampered["cryptographically_verified_release_signature_count"], 0)
        self.assertEqual(tampered["release_decision"], "NO_GO")

    def test_never_publish_a_secret_or_real_wallet_in_report(self):
        data = report(**self.docs)
        body = str(data)
        self.assertNotIn("private_key", body.lower())
        self.assertNotIn("mnemonic", body.lower())


if __name__ == "__main__":
    unittest.main()
