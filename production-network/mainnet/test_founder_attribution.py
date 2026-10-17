#!/usr/bin/env python3
"""Refuse wallet/ownership/legal status escalation based only on attribution."""
import copy
import json
from pathlib import Path
import unittest

from validate_founder_attribution import validate_attribution

HERE = Path(__file__).resolve().parent


class FounderAttributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads((HERE / "founder_attribution.json").read_text(encoding="utf-8"))

    def test_stated_founder_and_wallet_metadata_preserved(self):
        data = copy.deepcopy(self.doc)
        self.assertEqual(validate_attribution(data), [])
        self.assertEqual(data["organization"]["stated_owner_and_founder"]["full_name"], "Dario Canoy")
        self.assertEqual(data["organization"]["stated_owner_and_founder"]["public_title"], "Owner and Founder")
        self.assertEqual(data["founder_wallet"]["address"],
                         "0x1990589FD200E043b8C6FD9ec5956c61b3071048")
        self.assertEqual(data["organization"]["name"], "Privi World Corp.")

    def test_no_wallet_control_or_treasury_inference(self):
        for field in ("cryptographic_control_proof_verified",
                      "approved_for_financial_mainnet_genesis",
                      "treasury_multisig_or_validator_key"):
            doc = copy.deepcopy(self.doc)
            doc["founder_wallet"][field] = True
            self.assertTrue(validate_attribution(doc))

    def test_wallet_must_have_exact_20_byte_public_address_syntax(self):
        for wallet in ("0x1234", "privi1notanevmwallet",
                       "0x" + "z"*40, "0x" + "a"*42, "", None):
            doc = copy.deepcopy(self.doc)
            doc["founder_wallet"]["address"] = wallet
            self.assertTrue(validate_attribution(doc))

    def test_claimed_lawyer_signoff_is_not_an_independent_release_approval(self):
        self.assertTrue(self.doc["legal_review"]["claimed_signoff"])
        self.assertFalse(self.doc["legal_review"]["independent_legal_release_gate_satisfied"])
        for field, value in (("status", "VERIFIED_SIGNOFF"),
                             ("reviewer_identity_and_scope_verified", True),
                             ("independent_legal_release_gate_satisfied", True),
                             ("verified_signed_legal_opinion_sha256", "a"*64)):
            doc = copy.deepcopy(self.doc)
            doc["legal_review"][field] = value
            self.assertTrue(validate_attribution(doc))

    def test_cannot_claim_live_mainnet(self):
        doc = copy.deepcopy(self.doc)
        doc["financial_mainnet_activated"] = True
        self.assertTrue(validate_attribution(doc))

    def test_unrelated_financial_release_manifest_keeps_legal_gate_pending(self):
        manifest = json.loads((HERE / "manifest.example.json").read_text())
        self.assertEqual(manifest["assessments"]["independent_legal_review_url"], "")
        self.assertFalse(manifest["launch_authorization"]["manual_release_gate_open"])

    def test_public_founder_page_uses_only_canonical_values(self):
        readme = (HERE.parent.parent / "FOUNDER.md").read_text(encoding="utf-8")
        self.assertIn("Dario Canoy", readme)
        self.assertIn("Owner and Founder", readme)
        self.assertIn("Privi World Corp.", readme)
        self.assertIn(self.doc["founder_wallet"]["address"], readme)
        self.assertIn("self-declared", readme)


if __name__ == "__main__":
    unittest.main()
