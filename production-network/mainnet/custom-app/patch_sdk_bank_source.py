#!/usr/bin/env python3
"""Build a disposable PINNED Cosmos SDK module copy for bank hardening tests.

Protect external raw BaseKeeper MintCoins, UncheckedSetBalance and repeated
InitGenesis without
breaking *internal* legitimate bank sends and delegations. This is an
experimental preproduction SDK source modification, not an app release.
The immutable upstream module cache is READ ONLY: patched SDK lives in a
separate disposable module directory selected by Go's local replace directive. No validator state is touched.
"""
import argparse
import json
import shutil
import stat
from pathlib import Path

SDK_VERSION = "cosmos-sdk@v0.54.3"
SDK_DENOM = "aprvi"


def exact(text, before, after, tag, count=1):
    n = text.count(before)
    if n != count:
        raise ValueError(f"pinned Cosmos SDK source drift at {tag}: {n} matches, expected {count}")
    return text.replace(before, after)


def build_overlay(sdk_root: Path, output_dir: Path) -> dict:
    sdk_root = sdk_root.resolve(strict=True)
    if sdk_root.name != SDK_VERSION:
        raise ValueError("unapproved Cosmos SDK module root: requires v0.54.3")
    source = sdk_root / "x" / "bank" / "keeper"
    send_file = source / "send.go"
    keeper_file = source / "keeper.go"
    genesis_file = source / "genesis.go"
    send = send_file.read_text(encoding="utf-8")
    keeper = keeper_file.read_text(encoding="utf-8")
    genesis = genesis_file.read_text(encoding="utf-8")
    # Ensure upstream schema and exact package names before writing output.
    if not all(s.startswith("package keeper\n") for s in (send, keeper, genesis)):
        raise ValueError("unexpected Cosmos bank package")
    if send.count("func (k BaseSendKeeper) UncheckedSetBalance(") != 1:
        raise ValueError("unexpected upstream bank setter signature")
    # Native Cosmos bank sends/delegations must remain functional. The
    # public unsafe setter is no longer the path for internal operations.
    send = exact(
        send,
        "k.UncheckedSetBalance(ctx, addr, newBalance)",
        "k.setBalanceForBankOperation(ctx, addr, newBalance)",
        "send.go native balance movement", count=2,
    )
    keeper = exact(
        keeper,
        "k.UncheckedSetBalance(ctx, delegatorAddr, balance.Sub(coin))",
        "k.setBalanceForBankOperation(ctx, delegatorAddr, balance.Sub(coin))",
        "keeper.go delegated balance movement",
    )
    send = exact(
        send,
        "func (k BaseSendKeeper) UncheckedSetBalance(ctx context.Context, addr sdk.AccAddress, balance sdk.Coin) error {",
        "func (k BaseSendKeeper) setBalanceForBankOperation(ctx context.Context, addr sdk.AccAddress, balance sdk.Coin) error {",
        "bank-internal setter",
    )
    # The exported method remains on the official SDK keeper interface but
    # cannot write even ONE native aprvi to the underlying collections store.
    # Matching native no-ops remain permitted for upstream Cosmos EVM.
    send += '''
// UncheckedSetBalance is an EXTERNAL unsafe setter. The Privi build forbids
// native aprvi writes here, including via retained raw BaseKeeper copies.
// Real bank transfers use private setBalanceForBankOperation only.
func (k BaseSendKeeper) UncheckedSetBalance(ctx context.Context, addr sdk.AccAddress, balance sdk.Coin) error {
    if !balance.IsValid() {
        return errorsmod.Wrap(sdkerrors.ErrInvalidCoins, balance.String())
    }
    if balance.Denom == "aprvi" {
        prior := k.GetBalance(ctx, addr, balance.Denom)
        if prior.Amount.Equal(balance.Amount) {
            return nil // required zero-write Cosmos EVM state initialization
        }
        return fmt.Errorf("PRVI SDK bank: external native balance write forbidden")
    }
    return k.setBalanceForBankOperation(ctx, addr, balance)
}
'''
    # BaseKeeper.MintCoins has an unrestricted default on raw keeper copies;
    # restrict the RAW SDK method itself after the usual module-specific
    # MintRestriction check, preserving the keeper's original error handling.
    keeper = exact(
        keeper,
        '''\t\treturn err
\t}
\tacc := k.ak.GetModuleAccount(ctx, moduleName)
''',
        '''\t\treturn err
\t}
\tif amounts.AmountOf("aprvi").IsPositive() {
\t\treturn fmt.Errorf("PRVI SDK bank: native aprvi mint forbidden, including raw keeper copies")
\t}
\tacc := k.ak.GetModuleAccount(ctx, moduleName)
''',
        "SDK raw MintCoins entry",
    )
    # Reject invalid native genesis balances BEFORE any bank params/supply/KV
    # changes. This is enforced inside the pinned SDK bank implementation,
    # independent of custom app preflight and module initialization order.
    # The 1B PRVI lifetime cap is 10**27 base aprvi units. The 18 decimals
    # must NOT be handled with Go float/JS Number or a lossy int64.
    genesis = exact(
        genesis,
        "package keeper\n",
        "package keeper\n\nimport \"math/big\"\n",
        "pinned SDK genesis arbitrary-precision cap import",
    )
    genesis = exact(
        genesis,
        "    if genState == nil { panic(\"PRVI SDK bank: nil genesis refused\") }\n",
        """    if genState == nil { panic("PRVI SDK bank: nil genesis refused") }
    // PRVI genesis hard cap and actual bank allocation conservation. Validate
    // all native balance rows before SetParams, metadata or KV updates.
    nativeCap := new(big.Int).Exp(big.NewInt(10), big.NewInt(27), nil)
    nativeSupply := genState.Supply.AmountOf("aprvi").BigInt()
    if nativeSupply.Sign() < 0 || nativeSupply.Cmp(nativeCap) > 0 {
        panic("PRVI SDK bank: native genesis supply above hard cap")
    }
    nativeBalances := new(big.Int)
    for _, account := range genState.Balances {
        amount := account.Coins.AmountOf("aprvi").BigInt()
        if amount.Sign() < 0 {
            panic("PRVI SDK bank: negative native genesis balance")
        }
        nativeBalances.Add(nativeBalances, amount)
        if nativeBalances.Cmp(nativeCap) > 0 {
            panic("PRVI SDK bank: native genesis balances above hard cap")
        }
    }
    if nativeBalances.Cmp(nativeSupply) != 0 {
        panic("PRVI SDK bank: native genesis supply does not match balances")
    }
""",
        "genesis cap and allocation reconciliation guard",
    )
    # x/bank InitGenesis bypasses MintCoins and writes balances plus supply
    # directly. On the pinned bank schema, raw prefixes 0..5 are taken and
    # 0xff is reserved here for this preproduction one-shot guard. A distinct
    # consensus-store marker survives a native burn-to-zero. Never treat the
    # absence of this marker on an existing upgraded network as authorization
    # to initialize genesis again.
    genesis = exact(
        genesis,
        ")\n\n// InitGenesis initializes the bank module's state from a given genesis state.",
        ")\n\nvar priviBankGenesisApplied = []byte{0xff, 0x50, 0x52, 0x56, 0x49, 0x01}\n\n"
        "// InitGenesis initializes the bank module's state from a given genesis state.",
        "pinned SDK bank genesis marker",
    )
    genesis = exact(
        genesis,
        "func (k BaseKeeper) InitGenesis(ctx context.Context, genState *types.GenesisState) {\n",
        """func (k BaseKeeper) InitGenesis(ctx context.Context, genState *types.GenesisState) {
    // Reject before bank params, balances, or supply can be changed.
    if genState == nil { panic("PRVI SDK bank: nil genesis refused") }
    rawKV := k.storeService.OpenKVStore(ctx)
    already, err := rawKV.Has(priviBankGenesisApplied)
    if err != nil { panic(err) }
    if already || k.GetSupply(ctx, "aprvi").Amount.IsPositive() {
        panic("PRVI SDK bank: repeated InitGenesis forbidden")
    }
""",
        "genesis early lifecycle guard",
    )
    genesis = exact(
        genesis,
        """\tfor _, meta := range genState.DenomMetadata {
\t\tk.SetDenomMetaData(ctx, meta)
\t}
}""",
        """\tfor _, meta := range genState.DenomMetadata {
\t\tk.SetDenomMetaData(ctx, meta)
\t}
    // Only write the marker after genesis completed. Aborted InitChain must
    // be rolled back using the app's cached SDK context.
    if err := rawKV.Set(priviBankGenesisApplied, []byte{1}); err != nil { panic(err) }
}""",
        "genesis marker commit",
    )
    if "k.UncheckedSetBalance(" in send or "k.UncheckedSetBalance(" in keeper:
        raise ValueError("unreviewed SDK bank internal unsafe setter site")
    # Go explicitly refuses -overlay replacements for files underneath
    # GOMODCACHE. Instead copy the exact verified module to a throwaway
    # location and use a LOCAL go.mod replace only inside the CI workspace.
    # No writes to the cached module, any production node, or its data.
    output_dir = output_dir.resolve()
    if output_dir == sdk_root or sdk_root in output_dir.parents:
        raise ValueError("refusing SDK module cache overwrite")
    if output_dir.exists():
        raise ValueError("refusing to overwrite existing isolated SDK checkout")
    shutil.copytree(sdk_root, output_dir)
    target_send = output_dir / "x" / "bank" / "keeper" / "send.go"
    target_keeper = output_dir / "x" / "bank" / "keeper" / "keeper.go"
    target_genesis = output_dir / "x" / "bank" / "keeper" / "genesis.go"
    for target, patched in ((target_send, send), (target_keeper, keeper),
                            (target_genesis, genesis)):
        target.chmod(target.stat().st_mode | stat.S_IWUSR)
        target.write_text(patched, encoding="utf-8")
    return {"mode": "BUILD_ONLY_LOCAL_MODULE_REPLACEMENT",
            "financial_mainnet": "NO_GO",
            "sdk_module": SDK_VERSION, "module_dir": str(output_dir),
            "patched_files": ["x/bank/keeper/send.go", "x/bank/keeper/keeper.go",
                              "x/bank/keeper/genesis.go"]}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--sdk-root", required=True, type=Path)
    cli.add_argument("--output-dir", required=True, type=Path)
    args = cli.parse_args()
    print(json.dumps(build_overlay(args.sdk_root, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
