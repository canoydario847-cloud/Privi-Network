#!/usr/bin/env python3
"""Read-only initial PRVI bank supply audit for an unsigned candidate Cosmos genesis.

This audits genesis quantities; it DOES NOT demonstrate ongoing max-supply enforcement,
staking safety, vesting correctness or permissioned mint authority.
"""
import argparse
import json
import re
import sys
from pathlib import Path

CAP_COINS = 1_000_000_000
DECIMALS = 18
CAP_BASE = CAP_COINS * 10 ** DECIMALS
DENOM_PATTERN = re.compile(r"^[a-z][a-z0-9/]{2,63}$")

def parse_amount(raw, where):
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal():
        raise ValueError(where + ": amount must be a nonnegative base-10 integer string")
    return int(raw)

def audit(genesis, denom, chain_id):
    if not isinstance(genesis, dict):
        raise ValueError("genesis must be a JSON object")
    if not isinstance(denom, str) or not DENOM_PATTERN.fullmatch(denom):
        raise ValueError("invalid target base denomination")
    if not isinstance(chain_id, str) or not chain_id.strip() or chain_id == "local-4221":
        raise ValueError("a distinct planned mainnet Cosmos chain ID is required")
    if genesis.get("chain_id") != chain_id:
        raise ValueError("genesis chain_id does not match expected chain ID")
    bank = genesis.get("app_state", {}).get("bank", {})
    if not isinstance(bank, dict):
        raise ValueError("genesis app_state.bank missing or invalid")
    balances, supplies = bank.get("balances"), bank.get("supply")
    if not isinstance(balances, list) or not isinstance(supplies, list):
        raise ValueError("bank balances and supply must both be arrays")
    sum_balances = 0
    seen_addresses = set()
    account_count = 0
    for idx, row in enumerate(balances):
        if not isinstance(row, dict) or not isinstance(row.get("address"), str) or not row["address"].strip():
            raise ValueError("balance row %d missing address" % idx)
        address = row["address"]
        if address in seen_addresses:
            raise ValueError("duplicate bank address: " + address)
        seen_addresses.add(address)
        coins = row.get("coins")
        if not isinstance(coins, list):
            raise ValueError("account coins must be an array")
        local_denoms = set()
        for coin in coins:
            if not isinstance(coin, dict) or not isinstance(coin.get("denom"), str):
                raise ValueError("invalid coin entry")
            d = coin["denom"]
            if d in local_denoms:
                raise ValueError("duplicate denomination within account " + address)
            local_denoms.add(d)
            amount = parse_amount(coin.get("amount"), "balance for " + address)
            if d == denom:
                sum_balances += amount
        account_count += 1
    found_supply = None
    seen_supplies = set()
    for coin in supplies:
        if not isinstance(coin, dict) or not isinstance(coin.get("denom"), str):
            raise ValueError("invalid supply entry")
        d = coin["denom"]
        if d in seen_supplies:
            raise ValueError("duplicate denomination in bank supply")
        seen_supplies.add(d)
        amount = parse_amount(coin.get("amount"), "bank supply for " + d)
        if d == denom:
            found_supply = amount
    if found_supply is None:
        raise ValueError("PRVI denomination missing from bank supply")
    if found_supply != sum_balances:
        raise ValueError("PRVI bank supply differs from sum of PRVI bank balances")
    if found_supply > CAP_BASE:
        raise ValueError("initial PRVI bank supply exceeds proposed 1-billion-coin cap")
    if found_supply == 0:
        raise ValueError("genesis PRVI supply is zero; require explicit allocation review")
    return {
        "genesis_bank_audit": "PASS",
        "cosmos_chain_id": chain_id,
        "denom": denom,
        "base_decimals_assumed": DECIMALS,
        "genesis_supply_base_units": str(found_supply),
        "genesis_supply_whole_coins": str(found_supply // 10**DECIMALS),
        "max_supply_base_units": str(CAP_BASE),
        "bank_accounts_checked": account_count,
        "warning": "A one-time genesis bank check does not prove immutable cap enforcement, emissions, vesting, migration rights, or launch readiness"
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--genesis",required=True,type=Path)
    ap.add_argument("--denom",required=True)
    ap.add_argument("--chain-id",required=True)
    args=ap.parse_args()
    try:
        result=audit(json.loads(args.genesis.read_text(encoding="utf-8")),args.denom,args.chain_id)
    except (OSError, UnicodeError, ValueError, AttributeError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(json.dumps({"ok": True, **result},indent=2))
    return 0

if __name__=="__main__":
    sys.exit(main())
