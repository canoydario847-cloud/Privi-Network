"""Extra fail-closed source-patcher regressions; disposable synthetic SDK only."""
import unittest
from test_patch_sdk_bank_source import BankSDKOverlayTests, SEND, KEEPER, GENESIS

class MutationRegressions(BankSDKOverlayTests):
    def test_refuses_duplicate_native_mint_insertion_site(self):
        p=self.keeper/"keeper.go"
        p.write_text(KEEPER + "\n" + KEEPER.split("func (k BaseKeeper) MintCoins",1)[1].split("return nil",1)[0])
        with self.assertRaises(ValueError):
            self.assertIsNotNone(__import__("patch_sdk_bank_source").build_overlay(self.root,self.output))
        self.assertFalse(self.output.exists())

    def test_refuses_unexpected_bank_genesis_marker_location(self):
        p=self.keeper/"genesis.go"
        p.write_text(GENESIS.replace("// InitGenesis initializes", "// Changed upstream InitGenesis initializes"))
        import patch_sdk_bank_source as patch
        with self.assertRaises(ValueError):
            patch.build_overlay(self.root,self.output)
        self.assertFalse(self.output.exists())

    def test_refuses_altered_native_balance_setter_signature(self):
        p=self.keeper/"send.go"
        p.write_text(SEND.replace("func (k BaseSendKeeper) UncheckedSetBalance(", "func (k *BaseSendKeeper) UncheckedSetBalance("))
        import patch_sdk_bank_source as patch
        with self.assertRaises(ValueError):
            patch.build_overlay(self.root,self.output)
        self.assertFalse(self.output.exists())

if __name__ == "__main__":
    unittest.main()
