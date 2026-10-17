#!/usr/bin/env python3
"""Verify a proposed roster of SEVEN genuinely independent PRVI operators.

Input contains only public keys, public identity and evidence references.
This screening cannot independently attest ownership, verify signature
cryptography, procure hosts, or authorize a financial launch.
"""
import argparse
import base64
import binascii
import json
from pathlib import Path
from urllib.parse import urlsplit


def real_https(value):
    if not isinstance(value, str):
        return False
    u = urlsplit(value)
    return (u.scheme == "https" and bool(u.hostname)
            and u.username is None and u.password is None
            and not u.hostname.lower().endswith(
                (".example", ".test", ".invalid", ".localhost")))


def pubkey_bytes(value):
    if not isinstance(value, str):
        return None
    try:
        b = bytes.fromhex(value) if len(value) == 64 else base64.b64decode(value, validate=True)
        return b if len(b) == 32 else None
    except (ValueError, binascii.Error):
        return None


def screen(roster):
    errors = []
    rows = roster.get("operators") if isinstance(roster, dict) else None
    if not isinstance(rows, list) or len(rows) < 7:
        return ["Seven independent, non-placeholder operator records required"]

    unique = {k: set() for k in ("operator_id", "legal_controller_id",
               "signing_key_custodian_id", "cloud_account_owner_id", "consensus_pubkey")}
    providers, regions = set(), set()
    powers = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"operator {i}: entry is not an object")
            continue
        for key in unique:
            value = row.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"operator {i}: missing {key}")
                continue
            normalized = value.strip().lower() if key != "consensus_pubkey" else pubkey_bytes(value)
            if normalized is None:
                errors.append(f"operator {i}: public key must be 32-byte hex or Base64")
                continue
            if normalized in unique[key]:
                errors.append(f"operator {i}: duplicated {key} (not independent)")
            unique[key].add(normalized)
        for field in ("operator_independence_evidence_url", "custody_review_url",
                      "backup_rehearsal_url", "signed_genesis_attestation_url",
                      "oncall_runbook_url"):
            if not real_https(row.get(field)):
                errors.append(f"operator {i}: missing verifiable HTTPS {field}")
        for field, container in (("infrastructure_provider", providers), ("failure_region", regions)):
            value = row.get(field)
            if isinstance(value, str) and value.strip():
                container.add(value.strip().lower())
            else:
                errors.append(f"operator {i}: missing {field}")
        power = row.get("voting_power")
        if type(power) is not int or power <= 0:
            errors.append(f"operator {i}: positive integer voting power required")
        else:
            powers.append(power)
        for field in ("keys_exclusively_operator_controlled",
                      "independent_human_identity_reviewed",
                      "signed_genesis_attestation_crypto_verified",
                      "double_sign_fencing_rehearsed"):
            if row.get(field) is not True:
                errors.append(f"operator {i}: unresolved {field}")

    if len(providers) < 3:
        errors.append("at least 3 distinct infrastructure providers required")
    if len(regions) < 3:
        errors.append("at least 3 failure regions required")
    if len(powers) == len(rows) and powers:
        total = sum(powers)
        if any(3 * power >= total for power in powers):
            errors.append("operator with >=1/3 voting power violates independence gate")
    else:
        errors.append("voting power incomplete")

    if roster.get("independent_ownership_review_complete") is not True:
        errors.append("separate human beneficial-ownership review is required")
    if not real_https(roster.get("independent_ownership_review_url")):
        errors.append("missing verifiable external ownership-review evidence")
    if roster.get("status") != "PROPOSED_EXTERNAL_OPERATOR_ROSTER":
        errors.append("roster status must be PROPOSED_EXTERNAL_OPERATOR_ROSTER")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", required=True, type=Path)
    args = parser.parse_args()
    try:
        errors = screen(json.loads(args.roster.read_text(encoding="utf-8")))
    except (ValueError, OSError) as exc:
        errors = [str(exc)]
    if errors:
        print("INDEPENDENT OPERATORS NOT VERIFIED:")
        for item in errors:
            print(" -", item)
        return 1
    print("Roster self-reported structure passes. Identity, evidence, "
          "cryptography and independent control still require EXTERNAL review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
