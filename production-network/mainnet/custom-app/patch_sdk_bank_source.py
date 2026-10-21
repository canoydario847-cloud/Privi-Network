#!/usr/bin/env python3
"""Generate a Go overlay for a PINNED Cosmos SDK bank source (build/test only).

Protect external raw BaseKeeper MintCoins and UncheckedSetBalance without
breaking *internal* legitimate bank sends and delegations. This is an
experimental preproduction SDK source modification, not an app release.
The immutable upstream module cache is READ ONLY: overlays live in a
separate disposable output directory. No validator state is touched.
"""
import argparse
import json
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
    send = send_file.read_text(encoding="utf-8")
    keeper = keeper_file.read_text(encoding="utf-8")
    # Ensure upstream schema and exact package names before writing output.
    if not send.startswith("package keeper\n") or not keeper.startswith("package keeper\n"):
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
    if "k.UncheckedSetBalance(" in send or "k.UncheckedSetBalance(" in keeper:
        raise ValueError("unreviewed SDK bank internal unsafe setter site")
    # Prevent files being added alongside original SDK module source.
    output_dir = output_dir.resolve()
    if output_dir == sdk_root or sdk_root in output_dir.parents:
        raise ValueError("refusing SDK module cache overwrite")
    output_dir.mkdir(parents=True, exist_ok=True)
    target_send = output_dir / "send.go"
    target_keeper = output_dir / "keeper.go"
    target_send.write_text(send, encoding="utf-8")
    target_keeper.write_text(keeper, encoding="utf-8")
    overlay = output_dir / "overlay.json"
    mapping = {str(send_file): str(target_send), str(keeper_file): str(target_keeper)}
    overlay.write_text(json.dumps({"Replace": mapping}, indent=2) + "\n", encoding="utf-8")
    return {"mode": "BUILD_ONLY", "financial_mainnet": "NO_GO",
            "sdk_module": SDK_VERSION, "overlay": str(overlay), "files": sorted(mapping)}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--sdk-root", required=True, type=Path)
    cli.add_argument("--output-dir", required=True, type=Path)
    args = cli.parse_args()
    print(json.dumps(build_overlay(args.sdk_root, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
