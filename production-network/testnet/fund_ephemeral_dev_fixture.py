#!/usr/bin/env python3
"""Fund a disposable upstream Cosmos EVM dev-test fixture before first startup.

CI-only local-4221 / atest fixture. NEVER use with TEST public testnet or PRVI
production. Requires the explicit CI + opt-in environment guard; fail closed.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

FIXTURE_CHAIN = "local-4221"
DENOM = "atest"
ADDED_WEI = 10**24
NODES = ("node0", "node1", "node2", "node3")


def update_genesis(genesis, address):
    if not isinstance(genesis, dict) or genesis.get("chain_id") != FIXTURE_CHAIN:
        raise ValueError("refusing to edit non-local-4221 developer genesis")
    if not isinstance(address, str) or not address.startswith("cosmos1") or len(address) < 35:
        raise ValueError("expected a validated disposable Cosmos test account address")
    state = genesis.get("app_state")
    if not isinstance(state, dict) or not isinstance(state.get("bank"), dict):
        raise ValueError("missing bank genesis")
    bank = state["bank"]
    if not isinstance(bank.get("balances"), list) or not isinstance(bank.get("supply"), list):
        raise ValueError("missing bank balance/supply arrays")
    target = [x for x in bank["balances"] if isinstance(x, dict) and x.get("address") == address]
    if len(target) != 1:
        raise ValueError("account0 address absent or duplicated in genesis")
    funds = target[0].get("coins")
    if not isinstance(funds, list):
        raise ValueError("account has no coin array")
    coins = [x for x in funds if isinstance(x, dict) and x.get("denom") == DENOM]
    supplies = [x for x in bank["supply"] if isinstance(x, dict) and x.get("denom") == DENOM]
    if len(coins) != 1 or len(supplies) != 1:
        raise ValueError("missing/duplicate local atest denomination")
    bal, supply = coins[0], supplies[0]
    for value in (bal.get("amount"), supply.get("amount")):
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
            raise ValueError("invalid atest amount")
    # Refuse replay: original genesis account0 balance is far below funding amount.
    if int(bal["amount"]) >= ADDED_WEI:
        raise ValueError("account already appears modified; refusing double top-up")
    # Accounting preflight (all atest allocations must equal the bank supply).
    total = 0
    for acct in bank["balances"]:
        for coin in acct.get("coins", []):
            if coin.get("denom") == DENOM:
                total += int(coin["amount"])
    if total != int(supply["amount"]):
        raise ValueError("source bank genesis does not balance")
    bal["amount"] = str(int(bal["amount"]) + ADDED_WEI)
    supply["amount"] = str(int(supply["amount"]) + ADDED_WEI)
    return genesis


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--address", required=True)
    a = p.parse_args()
    if os.environ.get("CI") != "true" or os.environ.get("PRIVI_EPHEMERAL_TRANSFER_TEST") != "1":
        raise ValueError("CI-only opt-in fixture; never modify persistent/local mainnet files")
    root = a.root.resolve(strict=True)
    if root.name != ".testnets" or root.parent.name != ".upstream-evm":
        raise ValueError("refusing unexpected genesis root path")
    paths = [root / node / "evmd" / "config" / "genesis.json" for node in NODES]
    raw = [p.read_bytes() for p in paths]
    if len(set(hashlib.sha256(data).hexdigest() for data in raw)) != 1:
        raise ValueError("developer node genesis files are not byte-for-byte identical")
    candidate = update_genesis(json.loads(raw[0]), a.address)
    # No write until all validation has completed.
    serialized = (json.dumps(candidate, indent=2, ensure_ascii=False) + "\n").encode()
    for path in paths:
        path.write_bytes(serialized)
    print(json.dumps({"fixture": "LOCAL_VALUELESS_ATEST_ONLY",
                      "cosmos_chain_id": FIXTURE_CHAIN,
                      "account_funded": a.address, "funding_added_base_units": str(ADDED_WEI),
                      "genesis_sha256": hashlib.sha256(serialized).hexdigest(),
                      "nodes_modified": len(paths),
                      "warning": "NEVER use these insecure funded developer fixtures in public or financial networks"}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        sys.exit(1)
