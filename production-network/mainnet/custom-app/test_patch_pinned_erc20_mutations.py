"""Source-mutation safety tests, no Go execution, keys, or public chain."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

path=Path(__file__).with_name("patch_pinned_erc20_mutations.py")
spec=importlib.util.spec_from_file_location("privi_mutation_patch",path)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PARAMS='''package keeper
import (
\t"github.com/cosmos/evm/x/erc20/types"
)
func (k Keeper) SetParams(ctx sdk.Context, newParams types.Params) error {
\tk.setERC20Enabled(ctx, newParams.EnableErc20)
\tk.SetPermissionlessRegistration(ctx, newParams.PermissionlessRegistration)
\treturn nil
}
func (k Keeper) SetPermissionlessRegistration(ctx sdk.Context, permissionlessRegistration bool) {
\tstore := ctx.KVStore(k.storeKey)
\tif permissionlessRegistration {
\t\tstore.Set(types.ParamStoreKeyPermissionlessRegistration, isTrue)
\t\treturn
\t}
\tstore.Delete(types.ParamStoreKeyPermissionlessRegistration)
}
'''
PAIRS='''package keeper
import (
\t"github.com/ethereum/go-ethereum/common"
)
func (k *Keeper) SetToken(ctx sdk.Context, pair types.TokenPair) error {
\tif k.IsDenomRegistered(ctx, pair.Denom) {
\t\treturn nil
\t}
\tk.SetTokenPair(ctx, pair)
\tk.SetDenomMap(ctx, pair.Denom, pair.GetID())
\tk.SetERC20Map(ctx, pair.GetERC20Contract(), pair.GetID())
\treturn nil
}
func (k Keeper) SetTokenPair(ctx sdk.Context, tokenPair types.TokenPair) {
\tstore := prefix.NewStore(ctx.KVStore(k.storeKey), types.KeyPrefixTokenPair)
\tkey := tokenPair.GetID()
\tbz := k.cdc.MustMarshal(&tokenPair)
\tstore.Set(key, bz)
}
func (k Keeper) SetDenomMap(ctx sdk.Context, denom string, id []byte) {
\tstore := prefix.NewStore(ctx.KVStore(k.storeKey), types.KeyPrefixTokenPairByDenom)
\tstore.Set([]byte(denom), id)
}
'''

class NativeERC20PolicyTests(unittest.TestCase):
    def test_all_mutation_layers_deny_before_storage(self):
        a,b=mod.transformed(PARAMS,PAIRS)
        self.assertIn('SetPermissionlessRegistration(ctx sdk.Context, permissionlessRegistration bool) error',a)
        self.assertIn('return k.SetPermissionlessRegistration(ctx, false)',a)
        self.assertIn('if newParams.PermissionlessRegistration {',a)
        self.assertLess(a.index('if newParams.PermissionlessRegistration {'),
                        a.index('k.setERC20Enabled(ctx, newParams.EnableErc20)'))
        self.assertLess(a.index('if permissionlessRegistration {'),
                        a.index('ctx.KVStore(k.storeKey).Delete'))
        self.assertIn('if err := k.SetTokenPair(ctx, pair); err != nil { return err }',b)
        self.assertIn('if err := k.SetDenomMap(ctx, pair.Denom, pair.GetID()); err != nil { return err }',b)
        self.assertIn('func (k Keeper) SetTokenPair(ctx sdk.Context, tokenPair types.TokenPair) error',b)
        self.assertIn('func (k Keeper) SetDenomMap(ctx sdk.Context, denom string, id []byte) error',b)
        self.assertLess(b.index('if pair.Denom == "aprvi"'),
                        b.index('if k.IsDenomRegistered(ctx, pair.Denom)'))
        self.assertLess(b.index('if tokenPair.Denom == "aprvi"'),b.index('store.Set(key, bz)'))
        self.assertLess(b.index('if denom == "aprvi"'),
                        b.index('store.Set([]byte(denom), id)'))

    def test_invalid_pinned_params_rejected_without_fallback(self):
        broken=PARAMS.replace('SetPermissionlessRegistration(ctx, newParams.PermissionlessRegistration)',
                              'SetPermissionlessRegistration(ctx, true)')
        with self.assertRaisesRegex(ValueError,'pinned upstream mismatch'):
            mod.transformed(broken,PAIRS)

    def test_unexpected_duplicate_setter_rejected(self):
        with self.assertRaisesRegex(ValueError,'pinned upstream mismatch'):
            mod.transformed(PARAMS+PARAMS,PAIRS)

    def test_raw_pair_setter_changes_must_be_reviewed(self):
        broken=PAIRS.replace('store.Set(key, bz)','store.Set(append(key, 0), bz)')
        with self.assertRaisesRegex(ValueError,'pinned upstream mismatch'):
            mod.transformed(PARAMS,broken)

    def test_only_disposable_pinned_checkout_allowed(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError,"non-disposable"):
                mod.apply(root)

    def test_patcher_is_build_only_and_requires_pinned_commit(self):
        self.assertEqual(mod.PINNED,"c3ae9067a7eadcdea55a5192226916deb44c71c4")
        self.assertEqual(mod.DENOM,"aprvi")

if __name__=="__main__":
    unittest.main()
