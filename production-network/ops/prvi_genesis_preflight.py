#!/usr/bin/env python3
"""Fail-closed offline PRVI genesis supply preflight. NOT consensus enforcement."""
import argparse
import json
import sys
from pathlib import Path

MAX_GENESIS_FILE_BYTES = 8_000_000
# Cosmos bank integer amounts are bounded; never feed attacker-sized decimal
# strings into Python int(), which may raise or exhaust resources.
MAX_COIN_AMOUNT_DIGITS = 78

def unique_json_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate genesis JSON key: {key}")
        obj[key] = value
    return obj

def load_genesis(path):
    candidate = Path(path)
    if candidate.stat().st_size > MAX_GENESIS_FILE_BYTES:
        raise ValueError("genesis JSON exceeds 8 MB safety limit")
    with candidate.open(encoding="utf-8") as stream:
        return json.load(
            stream,
            object_pairs_hook=unique_json_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-JSON numeric constant: {value}")
            ),
        )

MAX_PRVI = 1_000_000_000
DECIMALS = 18
CAP = MAX_PRVI * 10**DECIMALS
DENOM = "aprvi"

def check(genesis):
    errors = []
    if not isinstance(genesis, dict) or not isinstance(genesis.get("app_state"), dict):
        return ["missing or malformed app_state"], 0
    app = genesis.get("app_state", {})
    bank = app.get("bank")
    if not isinstance(bank, dict):
        return ["missing or malformed bank state"], 0
    balances = bank.get("balances")
    if not isinstance(balances, list):
        return ["missing or malformed bank balances"], 0
    total = 0
    seen_addresses = set()
    seen_native = False
    balance_totals = {}
    for account in balances:
        if not isinstance(account, dict) or not isinstance(account.get("coins"), list):
            errors.append("malformed account or coin list")
            continue
        address = account.get("address")
        if not isinstance(address, str) or not address:
            errors.append("missing account address")
        elif address in seen_addresses:
            errors.append("duplicate account address")
        else:
            seen_addresses.add(address)
        seen_denoms = set()
        for coin in account.get("coins", []):
            if not isinstance(coin, dict) or not isinstance(coin.get("denom"), str):
                errors.append("malformed coin")
                continue
            denom = coin.get("denom")
            if denom in seen_denoms:
                errors.append("duplicate coin denom in account")
            seen_denoms.add(denom)
            amount_any = coin.get("amount")
            if not isinstance(amount_any, str) or not amount_any.isascii() or not amount_any.isdecimal() or len(amount_any) > MAX_COIN_AMOUNT_DIGITS or (len(amount_any) > 1 and amount_any.startswith("0")):
                errors.append("noncanonical native amount" if denom == DENOM else "noncanonical coin amount")
                continue
            value = int(amount_any)
            if value <= 0:
                errors.append("nonpositive coin amount")
            balance_totals[denom] = balance_totals.get(denom, 0) + value
            if denom != DENOM:
                continue
            seen_native = True
            amount = coin.get("amount")
            if not isinstance(amount, str) or not amount.isascii() or not amount.isdecimal() or len(amount) > MAX_COIN_AMOUNT_DIGITS or (len(amount) > 1 and amount.startswith("0")):
                errors.append("noncanonical native amount")
                continue
            n = int(amount)
            if n <= 0:
                errors.append("zero/negative native amount")
            total += n
    supply = bank.get("supply")
    if not isinstance(supply, list):
        return errors + ["missing or malformed bank supply"], total
    if any(not isinstance(coin, dict) or not isinstance(coin.get("denom"), str) for coin in supply):
        return errors + ["malformed bank supply coin"], total
    # Reject ambiguous duplicate supply entries, including non-native denoms.
    supply_denoms = set()
    supply_totals = {}
    for coin in supply:
        denom = coin.get("denom")
        if denom in supply_denoms:
            errors.append("duplicate supply denom")
        supply_denoms.add(denom)
        amount = coin.get("amount")
        if not isinstance(amount, str) or not amount.isascii() or not amount.isdecimal() or len(amount) > MAX_COIN_AMOUNT_DIGITS or (len(amount) > 1 and amount.startswith("0")):
            errors.append("noncanonical supply amount")
        else:
            supply_totals[denom] = int(amount)
    if balance_totals != supply_totals:
        errors.append("bank supply differs from balances across denominations")
    declared = [c.get("amount") for c in supply if c.get("denom") == DENOM]
    if len(declared) != 1 or not isinstance(declared[0], str) or not declared[0].isascii() or not declared[0].isdecimal() or len(declared[0]) > MAX_COIN_AMOUNT_DIGITS or (len(declared[0]) > 1 and declared[0].startswith("0")):
        errors.append("missing or malformed declared native supply")
    elif int(declared[0]) != total:
        errors.append("bank native supply differs from balances")
    if total > CAP:
        errors.append("native genesis supply exceeds 1B PRVI")
    if not seen_native:
        errors.append("native PRVI denomination absent from balances")
    if total == 0:
        errors.append("no positive native PRVI allocation")
    if not balances:
        errors.append("missing bank balances")
    return errors, total

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("genesis")
    args = parser.parse_args()
    try:
        genesis = load_genesis(args.genesis)
        errors, total = check(genesis)
    except (OSError, UnicodeError, ValueError) as exc:
        errors, total = [f"genesis input rejected: {exc}"], 0
    print(json.dumps({"denom": DENOM, "genesis_native_base_units": str(total), "cap_base_units": str(CAP), "errors": errors, "financial_mainnet_verdict": "NO_GO"}, indent=2))
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
