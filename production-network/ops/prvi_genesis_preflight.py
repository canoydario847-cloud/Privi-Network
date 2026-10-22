#!/usr/bin/env python3
"""Fail-closed offline PRVI genesis supply preflight. NOT consensus enforcement."""
import argparse
import json
import sys

MAX_PRVI = 1_000_000_000
DECIMALS = 18
CAP = MAX_PRVI * 10**DECIMALS
DENOM = "aprvi"

def check(genesis):
    errors = []
    app = genesis.get("app_state", {})
    balances = app.get("bank", {}).get("balances", [])
    total = 0
    seen_addresses = set()
    for account in balances:
        address = account.get("address")
        if not isinstance(address, str) or not address:
            errors.append("missing account address")
        elif address in seen_addresses:
            errors.append("duplicate account address")
        else:
            seen_addresses.add(address)
        seen_denoms = set()
        for coin in account.get("coins", []):
            denom = coin.get("denom")
            if denom in seen_denoms:
                errors.append("duplicate coin denom in account")
            seen_denoms.add(denom)
            if denom != DENOM:
                continue
            amount = coin.get("amount")
            if not isinstance(amount, str) or not amount.isascii() or not amount.isdecimal() or (len(amount) > 1 and amount.startswith("0")):
                errors.append("noncanonical native amount")
                continue
            n = int(amount)
            if n <= 0:
                errors.append("zero/negative native amount")
            total += n
    supply = app.get("bank", {}).get("supply", [])
    # Reject ambiguous duplicate supply entries, including non-native denoms.
    supply_denoms = set()
    for coin in supply:
        denom = coin.get("denom")
        if denom in supply_denoms:
            errors.append("duplicate supply denom")
        supply_denoms.add(denom)
    declared = [c.get("amount") for c in supply if c.get("denom") == DENOM]
    if len(declared) != 1 or not isinstance(declared[0], str) or not declared[0].isascii() or not declared[0].isdecimal() or (len(declared[0]) > 1 and declared[0].startswith("0")):
        errors.append("missing or malformed declared native supply")
    elif int(declared[0]) != total:
        errors.append("bank native supply differs from balances")
    if total > CAP:
        errors.append("native genesis supply exceeds 1B PRVI")
    if total == 0:
        errors.append("no positive native PRVI allocation")
    if not balances:
        errors.append("missing bank balances")
    return errors, total

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("genesis")
    args = parser.parse_args()
    with open(args.genesis, encoding="utf-8") as f:
        genesis = json.load(f)
    errors, total = check(genesis)
    print(json.dumps({"denom": DENOM, "genesis_native_base_units": str(total), "cap_base_units": str(CAP), "errors": errors, "financial_mainnet_verdict": "NO_GO"}, indent=2))
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
