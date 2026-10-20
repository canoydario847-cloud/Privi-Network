"""Offline-only negative tests for sole Privi World Corp founder wallet policy."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from verify_privi_single_owner import FOUNDER_WALLET, assess, main
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "privi_owner_wallet.candidate.json"

class FounderWalletPolicyTests(unittest.TestCase):
    def setUp(self):
        self.original = json.loads(TEMPLATE.read_text(encoding="utf-8"))

    def test_founder_wallet_exact_with_no_other_administrators(self):
        self.assertEqual(assess(self.original), [])
        self.assertEqual(len(FOUNDER_WALLET), 42)
        self.assertEqual(self.original["administrator_wallets"], [FOUNDER_WALLET])
        self.assertEqual(self.original["independent_operator_count"], 1)
        self.assertFalse(self.original["financial_launch_enabled"])

    def test_no_substitution_of_founder_administrator_or_treasury(self):
        for role in ("founder_public_wallet","network_owner_wallet",
                     "governance_admin_wallet","treasury_controller_wallet"):
            with self.subTest(role=role):
                row = copy.deepcopy(self.original)
                row[role] = "0x" + "7" * 40
                self.assertTrue(assess(row))

    def test_no_additional_admins_multisig_guardians_or_delegate(self):
        other = "0x" + "8"*40
        for key,value in (
            ("administrator_wallets",[FOUNDER_WALLET,other]),
            ("recovery_guardians",[other]),
            ("multisig_owners",[other]),
            ("delegate_administrators",[other]),
            ("independent_operator_count",2),
            ("validator_operator_count",4)
        ):
            with self.subTest(field=key):
                row = copy.deepcopy(self.original)
                row[key] = value
                self.assertTrue(assess(row))

    def test_no_foreign_token_issuance_fake_consensus_or_mainnet_activation(self):
        for key,value in (
            ("network","privi-mainnet"),
            ("startup_consensus","CometBFT PoS"),
            ("startup_consensus","Proof of Staked Authority"),
            ("third_party_token_bridges",True),
            ("proposed_max_supply_whole_prvi",1_000_000_001),
            ("proposed_native_symbol","PRIV"),
            ("financial_launch_enabled",True),
            ("real_prvi_issuance_enabled",True),
            ("signed_genesis_sha256","0"*64),
            ("native_pop_release_sha256","f"*64),
            ("production_validator_attestations","claimed"),
            ("status","LIVE")
        ):
            with self.subTest(field=key):
                row = copy.deepcopy(self.original)
                row[key] = value
                self.assertTrue(assess(row))

    def test_no_secrets_or_duplicate_json_keys(self):
        row = copy.deepcopy(self.original)
        row["private_key"] = "DO_NOT_STORE"
        self.assertTrue(assess(row))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "duplicated.json"
            p.write_text('{"network":"ok","network":"evil"}', encoding="utf-8")
            with patch("sys.argv",["verify_privi_single_owner.py",str(p),"--mode","draft"]):
                self.assertEqual(main(),3)

    def test_even_valid_proposed_owner_configuration_must_never_launch(self):
        with patch("sys.argv",["verify_privi_single_owner.py",str(TEMPLATE),"--mode","draft"]):
            self.assertEqual(main(),0)
        with patch("sys.argv",["verify_privi_single_owner.py",str(TEMPLATE),"--mode","launch"]):
            self.assertEqual(main(),3)

if __name__ == "__main__":
    unittest.main()
