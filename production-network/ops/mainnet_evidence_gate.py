#!/usr/bin/env python3
"""Fail-closed Privi financial-mainnet evidence gate. No network or wallet access."""
import argparse
import hashlib
import json
import pathlib
import sys

REQUIRED = (
    "audited_binary_sha256",
    "signed_genesis_sha256",
    "cosmos_chain_id",
    "evm_chain_id",
    "native_denom",
    "pop_consensus_audit",
    "supply_cap_consensus_test",
    "independent_validator_evidence",
    "public_testnet_report",
    "recovery_drill_report",
    "security_audit_report",
    "launch_approval",
)
PLACEHOLDERS = {"", "todo", "tbd", "pending", "unknown", "none", "not deployed"}
def check(data):
    errors = []
    for key in REQUIRED:
        value = data.get(key)
        if not isinstance(value, str) or value.strip().lower() in PLACEHOLDERS:
            errors.append(f"{key}: missing or placeholder")
    for key in ("audited_binary_sha256", "signed_genesis_sha256"):
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
            errors.append(f"{key}: expected 64 hexadecimal characters")
    if data.get("evm_chain_id") in ("262144", "4221"):
        errors.append("evm_chain_id: upstream demo identity is not approved production identity")
    if data.get("network") != "privi-financial-mainnet":
        errors.append("network: financial mainnet identity not explicitly declared")
    if data.get("test_asset_valueless") is not True:
        errors.append("test_asset_valueless: must be true")
    if data.get("bnb_priv_separate") is not True:
        errors.append("bnb_priv_separate: must be true")
    if data.get("production_mint_enabled") is not False:
        errors.append("production_mint_enabled: must be false during preflight")
    return errors

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=pathlib.Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.evidence.read_text())
        if not isinstance(data, dict):
            raise ValueError("Evidence must be a JSON object")
    except (OSError, ValueError) as exc:
        print(f"NO_GO: invalid evidence: {exc}")
        return 2
    errors = check(data)
    print(json.dumps({"status": "NO_GO" if errors else "PREFLIGHT_EVIDENCE_COMPLETE_NOT_LAUNCH_APPROVAL", "errors": errors}, indent=2))
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
