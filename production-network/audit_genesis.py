#!/usr/bin/env python3
"""Read-only PRVI genesis preflight; no keys, network, deployment or asset movement.
Usage: python3 production-network/audit_genesis.py /path/to/genesis.json
Exit 0 means structural checks pass, NOT authorization to launch.
"""
import json
import sys
from pathlib import Path

EXPECTED_DENOM = "ap rvi".replace(" ", "")  # configure explicitly if genesis denom differs
EXPECTED_CAP = 1_000_000_000 * 10**18  # only if PRVI uses 18 decimals
def audit(doc):
    problems = []
    app = doc.get("app_state", {})
    bank = app.get("bank", {})
    staking = app.get("staking", {}).get("params", {})
    mint = app.get("mint", {}).get("params", {})
    supply = {c.get("denom"): int(c.get("amount", "0")) for c in bank.get("supply", [])}
    balances = {}
    for entry in bank.get("balances", []):
        address = entry.get("address")
        if not address or address in balances:
            problems.append("Missing or duplicate balance address")
        balances[address] = entry
    total = {}
    for entry in balances.values():
        for coin in entry.get("coins", []):
            d = coin.get("denom")
            try:
                a = int(coin.get("amount", "0"))
                if a < 0: raise ValueError()
                total[d] = total.get(d, 0) + a
            except (ValueError, TypeError):
                problems.append("Invalid coin amount")
    for denom in set(supply) | set(total):
        if supply.get(denom, 0) != total.get(denom, 0):
            problems.append("Bank supply differs from summed balances: " + str(denom))
    if not doc.get("chain_id"):
        problems.append("Missing chain_id")
    if not doc.get("genesis_time"):
        problems.append("Missing genesis_time")
    if not app.get("genutil", {}).get("gen_txs"):
        problems.append("No genesis validator transactions found")
    if not staking.get("bond_denom"):
        problems.append("Missing staking bond denom")
    if not mint:
        problems.append("Missing mint module parameters; verify inflation controls manually")
    # This checker deliberately does not assert supply cap: cap and decimals must
    # be confirmed from chain source and approved economics before automation.
    return problems, {"chain_id": doc.get("chain_id"), "denoms": supply,
                      "balance_accounts": len(balances),
                      "genesis_txs": len(app.get("genutil", {}).get("gen_txs", [])),
                      "bond_denom": staking.get("bond_denom"),
                      "note": "Structural preflight only. Supply cap, POP consensus, signatures, vesting, validator independence and security audit are NOT verified."}
def main():
    if len(sys.argv) != 2:
        print("Usage: audit_genesis.py GENESIS.json", file=sys.stderr)
        return 2
    try:
        doc = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        problems, report = audit(doc)
        print(json.dumps({"status": "FAIL" if problems else "STRUCTURAL_PASS_ONLY",
                          "problems": problems, "report": report}, indent=2))
        return 1 if problems else 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}))
        return 1
if __name__ == "__main__":
    sys.exit(main())
