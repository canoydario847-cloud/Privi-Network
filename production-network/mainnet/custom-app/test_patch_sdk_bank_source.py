"""Fail-closed source-pinned bank overlay tests (no real SDK or chain)."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT=Path(__file__).with_name("patch_sdk_bank_source.py")
spec=importlib.util.spec_from_file_location("privi_sdk_bank_overlay",SCRIPT)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SEND="""package keeper
func (k BaseSendKeeper) subUnlockedCoins(ctx context.Context, addr sdk.AccAddress, amt sdk.Coins) error {
    newBalance := balance.Sub(coin)
    if err := k.UncheckedSetBalance(ctx, addr, newBalance); err != nil {
        return err
    }
}
func (k BaseSendKeeper) addCoins(ctx context.Context, addr sdk.AccAddress, amt sdk.Coins) error {
    err := k.UncheckedSetBalance(ctx, addr, newBalance)
    return err
}
func (k BaseSendKeeper) UncheckedSetBalance(ctx context.Context, addr sdk.AccAddress, balance sdk.Coin) error {
    return k.Balances.Set(ctx, collections.Join(addr,balance.Denom), balance.Amount)
}
"""
KEEPER="""package keeper
func (k BaseKeeper) DelegateCoins(ctx context.Context) error {
    err := k.UncheckedSetBalance(ctx, delegatorAddr, balance.Sub(coin))
    return err
}
func (k BaseKeeper) MintCoins(ctx context.Context, moduleName string, amounts sdk.Coins) error {
    if err := k.mintCoinsRestrictionFn(ctx, amounts); err != nil {
        return err
    }
    acc := k.ak.GetModuleAccount(ctx, moduleName)
    return nil
}
""".replace("    if err := k.mintCoinsRestrictionFn(ctx, amounts); err != nil {\n        return err\n    }\n    acc :=",
            "\terr := k.mintCoinsRestrictionFn(ctx, amounts)\n\tif err != nil {\n\t\treturn err\n\t}\n\tacc :=")
class BankSDKOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"cosmos-sdk@v0.54.3"
        self.keeper=self.root/"x"/"bank"/"keeper"
        self.keeper.mkdir(parents=True)
        (self.keeper/"send.go").write_text(SEND)
        (self.keeper/"keeper.go").write_text(KEEPER)
        self.output=Path(self.temp.name)/"overlay"
    def test_patches_only_private_sdk_bank_mutations_with_no_module_cache_edit(self):
        baseline=[(self.keeper/name).read_text() for name in ("send.go","keeper.go")]
        result=mod.build_overlay(self.root,self.output)
        overlay=json.loads(Path(result["overlay"]).read_text())["Replace"]
        changed_send=Path(overlay[str(self.keeper/"send.go")]).read_text()
        changed_keeper=Path(overlay[str(self.keeper/"keeper.go")]).read_text()
        self.assertIn("func (k BaseSendKeeper) setBalanceForBankOperation(",changed_send)
        self.assertIn("func (k BaseSendKeeper) UncheckedSetBalance(",changed_send)
        self.assertIn('balance.Denom == "aprvi"',changed_send)
        self.assertEqual(changed_send.count("k.setBalanceForBankOperation(ctx, addr, newBalance)"),2)
        self.assertIn("k.setBalanceForBankOperation(ctx, delegatorAddr",changed_keeper)
        self.assertIn('amounts.AmountOf("aprvi").IsPositive()',changed_keeper)
        self.assertEqual(baseline,[(self.keeper/name).read_text() for name in ("send.go","keeper.go")])
    def test_denies_unreviewed_sdk_signatures_and_does_not_write_overlay(self):
        (self.keeper/"send.go").write_text(SEND.replace("k.UncheckedSetBalance(ctx, addr, newBalance)", "k.AlternateSetBalance(ctx, addr, newBalance)",1))
        with self.assertRaisesRegex(ValueError,"source drift"):
            mod.build_overlay(self.root,self.output)
        self.assertFalse(self.output.exists())
    def test_denies_unknown_cosmos_sdk_release(self):
        wrong=self.root.with_name("cosmos-sdk@v0.54.4")
        self.root.rename(wrong)
        with self.assertRaisesRegex(ValueError,"requires v0.54.3"):
            mod.build_overlay(wrong,self.output)
    def test_denies_output_writes_into_go_module_cache(self):
        with self.assertRaisesRegex(ValueError,"refusing SDK module cache overwrite"):
            mod.build_overlay(self.root,self.root/"unsafe-overlay")

if __name__=="__main__":
    unittest.main()
