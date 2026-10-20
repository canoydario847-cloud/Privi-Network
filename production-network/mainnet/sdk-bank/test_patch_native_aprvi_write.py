"""Adversarial offline tests for pinned Cosmos SDK native write interceptor.

Run through offline checks without cloning Cosmos SDK or network access.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pinned_sdk_bank_patch", HERE / "patch_native_aprvi_write.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

spec2 = importlib.util.spec_from_file_location("pinned_sdk_positive_probe_patch", HERE / "patch_positive_probe.py")
probes = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(probes)

MINIMAL_SEND = """package keeper
func (k BaseSendKeeper) UncheckedSetBalance(ctx context.Context, addr sdk.AccAddress, balance sdk.Coin) error {
\tif !balance.IsValid() {
\t\treturn err
\t}
\treturn nil
}
func (k BaseSendKeeper) subUnlockedCoins() {
    if err := k.UncheckedSetBalance(ctx, addr, newBalance); err != nil {}
}
func (k BaseSendKeeper) addCoins() {
    err := k.UncheckedSetBalance(ctx, addr, newBalance)
}
"""
MINIMAL_KEEPER = """package keeper
func (k BaseKeeper) DelegateCoins() {
    err := k.UncheckedSetBalance(ctx, delegatorAddr, balance.Sub(coin))
}
"""
class PinnedSDKBankWriteGuardTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name) / ".privi-reviewed-sdk-copy"
        folder = self.dir / "x/bank/keeper"
        folder.mkdir(parents=True)
        (self.dir / "go.mod").write_text("module github.com/cosmos/cosmos-sdk\n", encoding="utf-8")
        (folder / "send.go").write_text(MINIMAL_SEND, encoding="utf-8")
        (folder / "keeper.go").write_text(MINIMAL_KEEPER, encoding="utf-8")

    def test_patcher_removes_internal_exports_but_not_public_api(self):
        result = mod.apply_patch(self.dir, verify_blobs=False)
        self.assertEqual(result["financial_mainnet"], "NO_GO")
        send = (self.dir / "x/bank/keeper/send.go").read_text()
        keeper = (self.dir / "x/bank/keeper/keeper.go").read_text()
        self.assertIn('balance.Denom == "aprvi"',send)
        self.assertEqual(send.count("k.UncheckedSetBalance("),0)
        self.assertEqual(keeper.count("k.UncheckedSetBalance("),0)
        self.assertIn("func (k BaseSendKeeper) UncheckedSetBalance(",send)
        self.assertIn("func (k BaseSendKeeper) priviSetBalanceInternal(",send)
        self.assertEqual(send.count("k.priviSetBalanceInternal("),3)
        self.assertEqual(keeper.count("k.priviSetBalanceInternal("),1)

    def test_refuses_non_disposable_source(self):
        with self.assertRaisesRegex(ValueError, "isolated"):
            mod.apply_patch(self.dir.parent, verify_blobs=False)

    def test_refuses_unreviewed_callsite_without_touching_files(self):
        path=self.dir/"x/bank/keeper/keeper.go"
        path.write_text(MINIMAL_KEEPER.replace("k.UncheckedSetBalance(","k.SomeOtherSetter("),encoding="utf-8")
        before=(self.dir/"x/bank/keeper/send.go").read_text()
        with self.assertRaises(ValueError):
            mod.apply_patch(self.dir, verify_blobs=False)
        self.assertEqual((self.dir/"x/bank/keeper/send.go").read_text(),before)

    def test_refuses_duplicate_exported_setter(self):
        path=self.dir/"x/bank/keeper/send.go"
        path.write_text(MINIMAL_SEND*2,encoding="utf-8")
        with self.assertRaises(ValueError):
            mod.apply_patch(self.dir, verify_blobs=False)

    def test_refuses_genesis_module_swap(self):
        (self.dir/"go.mod").write_text("module not.cosmos/sdk\n",encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not the pinned Cosmos SDK"):
            mod.apply_patch(self.dir,verify_blobs=False)

    def test_verifies_exact_blob_unless_explicit_fixture(self):
        with self.assertRaisesRegex(ValueError, "pinned v0.54.3"):
            mod.apply_patch(self.dir,verify_blobs=True)

    def test_positive_probe_single_reviewed_range(self):
        src = ("package main\n" + probes.MARKER_START + "\n"
               "    forbidden old test\n" + probes.MARKER_END + "\n")
        patched = probes.patch(src)
        self.assertNotIn("forbidden old test",patched)
        self.assertIn("SECURITY: app allowed unauthorized native direct balance write",patched)
        self.assertTrue(patched.endswith(probes.MARKER_END+"\n"))

    def test_positive_probe_duplicate_markers_fail(self):
        src=probes.MARKER_START+"\n"+probes.MARKER_START+"\n"+probes.MARKER_END
        with self.assertRaisesRegex(ValueError, "unique"):
            probes.patch(src)


if __name__ == "__main__":
    unittest.main()
