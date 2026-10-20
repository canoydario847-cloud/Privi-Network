#!/usr/bin/env python3
"""Build-only, fail-closed patch of pinned Cosmos EVM x/erc20 mutation paths.

No production deployment, token issuance, keys, transactions or network
access. The target must be the disposable exact pinned upstream checkout,
after creation of the custom app build workspace. This is NOT a complete
SDK/IBC/precompile proof or a deployable binary.
"""
import argparse
import subprocess
from pathlib import Path

PINNED = "c3ae9067a7eadcdea55a5192226916deb44c71c4"
DENOM = "aprvi"
PARAMS = Path("x/erc20/keeper/params.go")
PAIRS = Path("x/erc20/keeper/token_pairs.go")

def substitute_once(text, old, new, label):
    if text.count(old) != 1:
        raise ValueError("pinned upstream mismatch for " + label)
    return text.replace(old, new)

def transformed(params, pairs):
    params = substitute_once(params,
        'import (\n\t"github.com/cosmos/evm/x/erc20/types"',
        'import (\n\t"fmt"\n\t"github.com/cosmos/evm/x/erc20/types"',
        "ERC20 params import")
    params = substitute_once(params,
        '''func (k Keeper) SetParams(ctx sdk.Context, newParams types.Params) error {
\tk.setERC20Enabled(ctx, newParams.EnableErc20)
\tk.SetPermissionlessRegistration(ctx, newParams.PermissionlessRegistration)
\treturn nil
}''',
        '''func (k Keeper) SetParams(ctx sdk.Context, newParams types.Params) error {
\t// Never activate permissionless registration even during governance.
\t// Reject before mutating any consensus configuration state.
\tif newParams.PermissionlessRegistration {
\t\treturn fmt.Errorf("PRVI ERC20: permissionless registration forbidden")
\t}
\tk.setERC20Enabled(ctx, newParams.EnableErc20)
\treturn k.SetPermissionlessRegistration(ctx, false)
}''',
        "ERC20 SetParams pre-mutation denial")
    params = substitute_once(params,
        '''func (k Keeper) SetPermissionlessRegistration(ctx sdk.Context, permissionlessRegistration bool) {
\tstore := ctx.KVStore(k.storeKey)
\tif permissionlessRegistration {
\t\tstore.Set(types.ParamStoreKeyPermissionlessRegistration, isTrue)
\t\treturn
\t}
\tstore.Delete(types.ParamStoreKeyPermissionlessRegistration)
}''',
        '''func (k Keeper) SetPermissionlessRegistration(ctx sdk.Context, permissionlessRegistration bool) error {
\t// Reject even direct keeper calls before any state changes occur.
\tif permissionlessRegistration {
\t\treturn fmt.Errorf("PRVI ERC20: permissionless registration forbidden")
\t}
\tctx.KVStore(k.storeKey).Delete(types.ParamStoreKeyPermissionlessRegistration)
\treturn nil
}''',
        "ERC20 direct permissionless setter")
    pairs = substitute_once(pairs,
        'import (\n\t"github.com/ethereum/go-ethereum/common"',
        'import (\n\t"fmt"\n\t"github.com/ethereum/go-ethereum/common"',
        "ERC20 token pair import")
    pairs = substitute_once(pairs,
        '''func (k *Keeper) SetToken(ctx sdk.Context, pair types.TokenPair) error {
\tif k.IsDenomRegistered(ctx, pair.Denom) {''',
        '''func (k *Keeper) SetToken(ctx sdk.Context, pair types.TokenPair) error {
\tif pair.Denom == "aprvi" {
\t\treturn fmt.Errorf("PRVI ERC20: native aprvi registration forbidden")
\t}
\tif k.IsDenomRegistered(ctx, pair.Denom) {''',
        "ERC20 SetToken pre-mutation denial")
    pairs = substitute_once(pairs,
        '''\tk.SetTokenPair(ctx, pair)
\tk.SetDenomMap(ctx, pair.Denom, pair.GetID())
\tk.SetERC20Map(ctx, pair.GetERC20Contract(), pair.GetID())
\treturn nil''',
        '''\tif err := k.SetTokenPair(ctx, pair); err != nil { return err }
\tif err := k.SetDenomMap(ctx, pair.Denom, pair.GetID()); err != nil { return err }
\tk.SetERC20Map(ctx, pair.GetERC20Contract(), pair.GetID())
\treturn nil''',
        "ERC20 SetToken indexed writes")
    pairs = substitute_once(pairs,
        '''func (k Keeper) SetTokenPair(ctx sdk.Context, tokenPair types.TokenPair) {
\tstore := prefix.NewStore(ctx.KVStore(k.storeKey), types.KeyPrefixTokenPair)
\tkey := tokenPair.GetID()
\tbz := k.cdc.MustMarshal(&tokenPair)
\tstore.Set(key, bz)
}''',
        '''func (k Keeper) SetTokenPair(ctx sdk.Context, tokenPair types.TokenPair) error {
\t// Do not store a native aprvi pair, even disabled, from upgrade or
\t// direct keeper call paths. Callers must not ignore this error.
\tif tokenPair.Denom == "aprvi" {
\t\treturn fmt.Errorf("PRVI ERC20: native aprvi token pair forbidden")
\t}
\tstore := prefix.NewStore(ctx.KVStore(k.storeKey), types.KeyPrefixTokenPair)
\tkey := tokenPair.GetID()
\tbz := k.cdc.MustMarshal(&tokenPair)
\tstore.Set(key, bz)
\treturn nil
}''',
        "ERC20 raw pair setter")
    pairs = substitute_once(pairs,
        '''func (k Keeper) SetDenomMap(ctx sdk.Context, denom string, id []byte) {
\tstore := prefix.NewStore(ctx.KVStore(k.storeKey), types.KeyPrefixTokenPairByDenom)
\tstore.Set([]byte(denom), id)
}''',
        '''func (k Keeper) SetDenomMap(ctx sdk.Context, denom string, id []byte) error {
\tif denom == "aprvi" {
\t\treturn fmt.Errorf("PRVI ERC20: native aprvi denom index forbidden")
\t}
\tstore := prefix.NewStore(ctx.KVStore(k.storeKey), types.KeyPrefixTokenPairByDenom)
\tstore.Set([]byte(denom), id)
\treturn nil
}''',
        "ERC20 denom index setter")
    return params, pairs

def apply(upstream):
    upstream = Path(upstream).resolve(strict=True)
    if upstream.name != ".upstream-capbuild" or not upstream.is_dir():
        raise ValueError("refusing non-disposable checkout")
    sha = subprocess.check_output(["git","-C",str(upstream),"rev-parse","HEAD"],text=True).strip()
    if sha != PINNED:
        raise ValueError("upstream commit differs from reviewed pinned version")
    tracked = subprocess.check_output(["git","-C",str(upstream),"status","--porcelain","--",
                                       str(PARAMS),str(PAIRS)],text=True).strip()
    if tracked:
        raise ValueError("refusing modified upstream ERC20 keeper source")
    a, b = upstream/PARAMS, upstream/PAIRS
    old_a,old_b = a.read_text(encoding="utf-8"),b.read_text(encoding="utf-8")
    new_a,new_b = transformed(old_a,old_b)   # validate every anchor BEFORE writes
    if new_a == old_a or new_b == old_b:
        raise ValueError("ERC20 policy patch did not modify both keeper files")
    a.write_text(new_a,encoding="utf-8")
    b.write_text(new_b,encoding="utf-8")
    return {
        "status":"BUILD_ONLY_NATIVE_ERC20_PREMUTATION_DENIAL_PATCHED",
        "files":[str(PARAMS),str(PAIRS)],
        "upstream_commit":PINNED,
        "financial_mainnet":"NOT_ACTIVE",
        "limitations":"Additional downstream mutation callers, VM/IBC and upgrades require audit",
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--upstream",required=True,type=Path)
    args=ap.parse_args()
    import json
    print(json.dumps(apply(args.upstream),indent=2))

if __name__=="__main__":
    main()
