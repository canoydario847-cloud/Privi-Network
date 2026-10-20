#!/usr/bin/env python3
"""Experimental, source-pinned Cosmos SDK v0.54.3 bank native write control.

A disposable SDK SOURCE COPY is required; no installed SDK, production host,
chain database, private key or active financial network is changed.

This explicitly separates internal SDK transfer/delegation balance writes
from the public UncheckedSetBalance method, which must refuse native aprvi
writes regardless of amount. Bank genesis writes via SDK collection imports.

INCOMPLETE FOR FINANCIAL RELEASE: raw .Balances.Set / consensus KV and upgrades
may bypass this API, and all IBC/EVM/staking access paths need a real audit.
"""
import argparse
import re
import subprocess
from pathlib import Path

SDK_TAG = "v0.54.3"
SDK_COMMIT = "046046a6731ddc00bca29193f5f0529d7017b3e3"
# Immutable blob object IDs from the reviewed public SDK tag.
BANK_SEND_BLOB = "7fbba171c7daff3e4cbc975b10fab97307439593"
BANK_KEEPER_BLOB = "103918dfb965b91bddb469aa0031b82f9b373531"
DENOM = "aprvi"


def replace_exact(source, target, replacement, reason, expected=1):
    found = source.count(target)
    if found != expected:
        raise ValueError(f"{reason}: pinned upstream occurrence mismatch: {found}, expected {expected}")
    return source.replace(target, replacement)


def git_blob(path):
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def apply_patch(sdk_copy, *, verify_blobs=True):
    copy = Path(sdk_copy).resolve(strict=True)
    if copy.name != ".privi-reviewed-sdk-copy" or not copy.is_dir():
        raise ValueError("SDK patch must target an isolated .privi-reviewed-sdk-copy only")
    manifest = copy / "go.mod"
    if not manifest.is_file() or not re.search(
        r"(?m)^module github\.com/cosmos/cosmos-sdk\\s*$",
        manifest.read_text(encoding="utf-8"),
    ):
        raise ValueError("not the pinned Cosmos SDK source module")
    send_file = copy / "x/bank/keeper/send.go"
    keeper_file = copy / "x/bank/keeper/keeper.go"
    if verify_blobs:
        if git_blob(send_file) != BANK_SEND_BLOB or git_blob(keeper_file) != BANK_KEEPER_BLOB:
            raise ValueError("SDK bank source differs from pinned v0.54.3 tag blobs")
    send = send_file.read_text(encoding="utf-8")
    keeper = keeper_file.read_text(encoding="utf-8")
    send = replace_exact(send, "k.UncheckedSetBalance(ctx, addr, newBalance)",
                         "k.priviSetBalanceInternal(ctx, addr, newBalance)",
                         "internal SDK send add/sub balance", expected=2)
    keeper = replace_exact(keeper,
                           "k.UncheckedSetBalance(ctx, delegatorAddr, balance.Sub(coin))",
                           "k.priviSetBalanceInternal(ctx, delegatorAddr, balance.Sub(coin))",
                           "internal SDK staking delegation")
    declaration = (
        "func (k BaseSendKeeper) UncheckedSetBalance(ctx context.Context, addr sdk.AccAddress, balance sdk.Coin) error {\n"
        "\tif !balance.IsValid() {"
    )
    replacement = (
        "// Public unchecked account rewrites of native PRVI must never be a\n"
        "// fallback transfer path. SDK-owned send/delegate internals use the\n"
        "// separate private method below. This is a fail-closed app policy.\n"
        "func (k BaseSendKeeper) UncheckedSetBalance(ctx context.Context, addr sdk.AccAddress, balance sdk.Coin) error {\n"
        "\tif balance.Denom == \"aprvi\" {\n"
        "\t\treturn fmt.Errorf(\"PRVI forbidden direct unchecked native account balance write\")\n"
        "\t}\n"
        "\treturn k.priviSetBalanceInternal(ctx, addr, balance)\n"
        "}\n\n"
        "// priviSetBalanceInternal is callable only by reviewed SDK x/bank\n"
        "// source paths; this is NOT a general authorization log.\n"
        "func (k BaseSendKeeper) priviSetBalanceInternal(ctx context.Context, addr sdk.AccAddress, balance sdk.Coin) error {\n"
        "\tif !balance.IsValid() {"
    )
    send = replace_exact(send, declaration, replacement, "exported bank setter guard")
    if send.count("k.UncheckedSetBalance(") or keeper.count("k.UncheckedSetBalance("):
        raise ValueError("an SDK internal direct balance setter call remains unreviewed")
    if send.count("k.priviSetBalanceInternal(") != 3 or keeper.count(
        "k.priviSetBalanceInternal("
    ) != 1:
        raise ValueError("SDK internal bank balance setter paths mismatch")
    # Never write partially: both source files pass all source checks first.
    send_file.write_text(send, encoding="utf-8")
    keeper_file.write_text(keeper, encoding="utf-8")
    return {"status": "EXPERIMENTAL_VALUELESS_SDK_NATIVE_WRITE_GUARD",
            "tag": SDK_TAG, "commit": SDK_COMMIT,
            "modified_paths": ["x/bank/keeper/send.go", "x/bank/keeper/keeper.go"],
            "financial_mainnet": "NO_GO",
            "limitations": "API guard only: direct collection writes and upgrades are not prohibited"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sdk-copy", type=Path, required=True)
    args = ap.parse_args()
    import json
    print(json.dumps(apply_patch(args.sdk_copy), indent=2))


if __name__ == "__main__":
    main()
