#!/usr/bin/env python3
"""Verify the UNSIGNED Privi 1-billion-native-coin allocation worksheet.

No blockchain, wallet, signing key, RPC, cloud or token issuance is accessed.
The COUNSEL-PACKET proportions are a proposal, NOT approved wallet payouts.
A successful --mode draft proves arithmetic only. Production mode is always
NO-GO until an external complete release/host/genesis/security verification.

Uses the strict JSON evidence loader to reject duplicate keys and secrets.
"""
import argparse
import json
import re
from pathlib import Path

from strict_json_evidence import load

DECIMALS = 18
CAP = 1_000_000_000
BASE = 10 ** DECIMALS
ALLOCATION = {
    "community": 400_000_000,
    "ecosystem": 200_000_000,
    "staking_reserve": 200_000_000,
    "treasury": 100_000_000,
    "contributors": 100_000_000,
}
ROOT_KEYS = {
    "schema_version", "network", "asset", "base_denom", "decimals",
    "maximum_whole_prvi", "proposed_genesis_whole_prvi",
    "state", "policy", "cosmos_chain_id", "evm_chain_id",
    "signed_genesis_sha256", "signed_release_sha256",
    "independent_security_review", "final_go_authorization", "allocations",
}
ALLOCATION_KEYS = {
    "bucket", "whole_prvi", "base_aprvi", "recipient_public_address",
    "vesting_terms", "approval_reference",
}
UNASSIGNED = "UNASSIGNED"
CANONICAL = re.compile(r"^(0|[1-9][0-9]*)$")


def checked_int(raw, place):
    if type(raw) is not str or len(raw) > 80 or not CANONICAL.fullmatch(raw):
        raise ValueError(place + " must be a canonical decimal string")
    return int(raw)


def validate(plan):
    """Return count and sums, never mint tokens or certify accounts/keys."""
    if type(plan) is not dict or set(plan) != ROOT_KEYS:
        raise ValueError("issuance plan has missing or unexpected properties")
    pins = {
        "schema_version": 1,
        "network": "PRVI_FINANCIAL_CANDIDATE_NOT_DEPLOYED",
        "asset": "PRVI",
        "base_denom": "aprvi",
        "decimals": DECIMALS,
        "state": "UNSIGNED_DRAFT_NOT_MINTED",
        "policy": "COUNSEL_PACKET_PROPOSAL_NOT_FINAL_ALLOCATION_APPROVAL",
    }
    for k, expected in pins.items():
        if type(plan.get(k)) is not type(expected) or plan[k] != expected:
            raise ValueError(k + " differs from the nonfinancial unsigned review plan")
    if checked_int(plan["maximum_whole_prvi"],"max supply") != CAP:
        raise ValueError("PRVI maximum changed")
    if checked_int(plan["proposed_genesis_whole_prvi"], "genesis proposal") != CAP:
        raise ValueError("genesis allocation proposal must equal the reviewed draft total")
    # Enforce still incomplete: neither a forged signing claim nor a
    # production endpoint may be introduced through this reviewed draft.
    for k in ("cosmos_chain_id","evm_chain_id","signed_genesis_sha256",
              "signed_release_sha256","independent_security_review",
              "final_go_authorization"):
        if plan[k] != UNASSIGNED:
            raise ValueError(k + " may not be asserted in an unsigned draft")
    rows=plan.get("allocations")
    if type(rows) is not list or len(rows) != len(ALLOCATION):
        raise ValueError("expected exactly five proposed PRVI allocation buckets")
    seen=set()
    total=0
    for row in rows:
        if type(row) is not dict or set(row) != ALLOCATION_KEYS:
            raise ValueError("invalid allocation row")
        name=row["bucket"]
        if type(name) is not str or name not in ALLOCATION or name in seen:
            raise ValueError("unknown or duplicate PRVI allocation bucket")
        seen.add(name)
        amount=checked_int(row["whole_prvi"],"whole PRVI")
        base=checked_int(row["base_aprvi"],"aprvi base units")
        if amount != ALLOCATION[name] or base != amount*BASE:
            raise ValueError("draft bucket allocation does not reconcile")
        total+=base
        for k in ("recipient_public_address", "vesting_terms", "approval_reference"):
            if row[k] != UNASSIGNED:
                raise ValueError("do not assign recipient or vesting without separate release review")
    if seen != set(ALLOCATION) or total != CAP*BASE:
        raise ValueError("genesis sum not 1B PRVI / 10^27 aprvi")
    return {"status":"UNSIGNED_DRAFT_ARITHMETIC_ONLY","denom":"aprvi",
            "whole_prvi":str(total//BASE),"base_aprvi":str(total),
            "bucket_count":len(seen),"financial_mainnet":"NOT_LIVE",
            "coins_minted":"0"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest",type=Path)
    p.add_argument("--mode",choices=("draft","launch"),default="draft")
    options=p.parse_args()
    try:
        outcome=validate(load(options.manifest))
    except (OSError,ValueError,UnicodeError) as exc:
        print(json.dumps({"ok":False,"status":"INVALID_UNSIGNED_PLAN","error":str(exc)}))
        return 2
    print(json.dumps({"ok":True,**outcome},indent=2))
    if options.mode=="launch":
        print("NO-GO: unsigned arithmetic proposal does not authorize any financial issuance or validator start")
        return 3
    return 0


if __name__=="__main__":
    raise SystemExit(main())
