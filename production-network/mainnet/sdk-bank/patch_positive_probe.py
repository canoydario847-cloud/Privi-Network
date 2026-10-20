#!/usr/bin/env python3
"""Patch a disposable positive genesis probe to assert guarded bank writes.

Modifies ONLY an explicit single-purpose executable copied into disposable
Cosmos EVM source, never the shared production-network test source.
"""
import argparse
from pathlib import Path

MARKER_START = "    // Simulate a dangerous direct x/bank UncheckedSetBalance write:"
MARKER_END = "    // Execute real Cosmos SDK Begin/EndBlock via ABCI FinalizeBlock on the"
TEST_REPLACEMENT = """    // With the reviewed bank SDK write restriction installed, direct aprvi
    // rewrites must fail at the API, before the block-boundary invariant.
    original:=app.BankKeeper.GetBalance(ctx,address,prvicap.BaseDenom)
    if err:=app.BankKeeper.UncheckedSetBalance(ctx,address,
        sdk.NewCoin(prvicap.BaseDenom,original.Amount.Add(sdkmath.NewInt(1))));err==nil {
        return fmt.Errorf("SECURITY: app allowed unauthorized native direct balance write")
    }
    if got:=app.BankKeeper.GetBalance(ctx,address,prvicap.BaseDenom);!got.IsEqual(original) {
        return fmt.Errorf("SECURITY: rejected direct balance write mutated account")
    }
    if err:=app.PriviCapKeeper.Reconcile(ctx,app.BankKeeper);err!=nil {
        return fmt.Errorf("rejected native direct write left invalid supply: %w",err)
    }
    fmt.Println("PASS: pinned SDK denied actual aprvi UncheckedSetBalance; bank invariant preserved")

"""


def patch(src):
    first = src.find(MARKER_START)
    second = src.find(MARKER_END)
    if first < 0 or second < first:
        raise ValueError("positive probe audit markers absent or out of order")
    if src.count(MARKER_START) != 1 or src.count(MARKER_END) != 1:
        raise ValueError("positive probe markers must be unique")
    return src[:first] + TEST_REPLACEMENT + src[second:]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--disposable-probe", type=Path, required=True)
    p = ap.parse_args().disposable_probe.resolve(strict=True)
    if p.parent.name != "privi-cap-genesis-positive-probe" or p.name != "main.go":
        raise ValueError("refusing to patch non-disposable positive probe")
    source = p.read_text(encoding="utf-8")
    result = patch(source)
    p.write_text(result, encoding="utf-8")
    print("PASS: disposable full-app positive probe now tests direct aprvi write denial")


if __name__ == "__main__":
    main()
