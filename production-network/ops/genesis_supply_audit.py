#!/usr/bin/env python3
"""Read-only initial PRVI bank supply audit for an unsigned candidate Cosmos genesis.

Fail-closed against duplicate JSON keys, oversized input, noncanonical amounts,
and inconsistent bank supply in ANY denomination. This is NOT lifetime supply
enforcement, vesting/staking review, signer approval or mainnet activation.
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
MAX_GENESIS_FILE_BYTES = 8_000_000
MAX_COIN_AMOUNT_DIGITS = 78


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate genesis JSON key: " + key)
        result[key] = value
    return result


def _reject_non_json_number(token):
    raise ValueError("invalid JSON numeric constant: " + token)


def parse_strict_json_bytes(raw):
    """Parse the EXACT bytes being audited; no ignored duplicate JSON members."""
    if not isinstance(raw, bytes) or len(raw) > MAX_GENESIS_FILE_BYTES:
        raise ValueError("genesis JSON exceeds 8 MB safety limit or is not bytes")
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_non_json_number,
    )


def load_strict_genesis(path):
    """Bound the actual read, not only a potentially stale stat() result."""
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_GENESIS_FILE_BYTES + 1)
    return parse_strict_json_bytes(raw)


def parse_amount(raw, where):
    if (not isinstance(raw, str) or not raw.isascii() or
        not raw.isdecimal() or len(raw) > MAX_COIN_AMOUNT_DIGITS or
        (len(raw) > 1 and raw.startswith("0"))):
        raise ValueError(where + ": noncanonical nonnegative base-10 integer amount")
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
    app_state = genesis.get("app_state")
    if not isinstance(app_state, dict):
        raise ValueError("genesis app_state missing or invalid")
    bank = app_state.get("bank")
    if not isinstance(bank, dict):
        raise ValueError("genesis app_state.bank missing or invalid")
    balances, supplies = bank.get("balances"), bank.get("supply")
    if not isinstance(balances, list) or not isinstance(supplies, list):
        raise ValueError("bank balances and supply must both be arrays")

    balances_by_denom = {}
    seen_addresses = set()
    for idx, row in enumerate(balances):
        if (not isinstance(row, dict) or
            not isinstance(row.get("address"), str) or not row["address"].strip()):
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
            if (not isinstance(coin, dict) or
                not isinstance(coin.get("denom"), str) or not coin["denom"]):
                raise ValueError("invalid coin entry")
            d = coin["denom"]
            if d in local_denoms:
                raise ValueError("duplicate denomination within account " + address)
            local_denoms.add(d)
            amount = parse_amount(coin.get("amount"), "balance for " + address)
            if amount == 0:
                raise ValueError("zero bank balance coin forbidden")
            balances_by_denom[d] = balances_by_denom.get(d, 0) + amount

    supply_by_denom = {}
    for coin in supplies:
        if (not isinstance(coin, dict) or
            not isinstance(coin.get("denom"), str) or not coin["denom"]):
            raise ValueError("invalid supply entry")
        d = coin["denom"]
        if d in supply_by_denom:
            raise ValueError("duplicate denomination in bank supply")
        amount = parse_amount(coin.get("amount"), "bank supply for " + d)
        if amount == 0:
            raise ValueError("zero bank supply coin forbidden")
        supply_by_denom[d] = amount

    if denom not in supply_by_denom:
        raise ValueError("PRVI denomination missing from bank supply")
    if supply_by_denom != balances_by_denom:
        raise ValueError("bank supply differs from sum of bank balances across denominations")
    found_supply = supply_by_denom[denom]
    if found_supply > CAP_BASE:
        raise ValueError("initial PRVI bank supply exceeds proposed 1-billion-coin cap")

    return {
        "genesis_bank_audit": "PASS",
        "cosmos_chain_id": chain_id,
        "denom": denom,
        "base_decimals_assumed": DECIMALS,
        "genesis_supply_base_units": str(found_supply),
        "genesis_supply_whole_coins": str(found_supply // 10**DECIMALS),
        "max_supply_base_units": str(CAP_BASE),
        "bank_accounts_checked": len(balances),
        "bank_denominations_reconciled": len(supply_by_denom),
        "warning": "One-time genesis bank accounting cannot prove immutable lifetime cap enforcement, emissions, vesting, consensus, or release readiness",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--genesis", required=True, type=Path)
    ap.add_argument("--denom", required=True)
    ap.add_argument("--chain-id", required=True)
    args = ap.parse_args()
    try:
        result = audit(load_strict_genesis(args.genesis), args.denom, args.chain_id)
    except (OSError, UnicodeError, ValueError, AttributeError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
