"""Static regression checks for the build-only PRVI SDK bank patch.

These tests do not establish transactional atomicity or production readiness.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent

class BankMutationBoundaryTests(unittest.TestCase):
    def test_raw_mint_and_balance_setter_are_guarded(self):
        source = (ROOT / "patch_sdk_bank_source.py").read_text()
        self.assertIn('amounts.AmountOf(', source)
        self.assertIn('balance.Denom ==', source)
        self.assertIn('setBalanceForBankOperation', source)

    def test_app_checks_supply_at_both_block_boundaries(self):
        source = (ROOT / "apply_prvi_cap.py").read_text()
        self.assertIn('PRVI begin-block supply check', source)
        self.assertIn('PRVI end-block supply check', source)
        self.assertIn('app.PriviCapKeeper.InitGenesis', source)

    def test_prototype_cannot_substitute_for_consensus_rollback(self):
        source = (ROOT.parent / "mintguard" / "guard.go").read_text()
        self.assertIn('OFF-CHAIN prototype', source)
        self.assertIn('single consensus cache context', source)

if __name__ == "__main__":
    unittest.main()
