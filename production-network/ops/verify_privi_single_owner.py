#!/usr/bin/env python3
"""Fail-closed proposed founder-wallet governance guard.

This verifies an UNSIGNED administrative configuration only. It never
authorizes finance, produces a genesis, provisions validators, loads private
keys, or claims real PoP consensus. Network launch ALWAYS refuses.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from strict_json_evidence import load as load_strict_json, reject_secrets

FOUNDER_WALLET = "0x1990589FD200E043b8C6FD9ec5956c61b3071048"
EXPECTED_ROLE_KEYS = (
    "founder_public_wallet",
    "network_owner_wallet",
    "governance_admin_wallet",
    "treasury_controller_wallet",
)
ALLOWED_NETWORK = "privi-financial-candidate-NOT_DEPLOYED"
HEX_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")


def assess(manifest):
    """Returns a list of failures; no evaluation here grants deployment."""
    errors = []
    if not isinstance(manifest, dict):
        return ["owner manifest must be a JSON object"]

    try:
        reject_secrets(manifest)
    except ValueError:
        errors.append("prohibited credential material in public wallet manifest")

    def require(ok, message):
        if not ok:
            errors.append(message)

    require(manifest.get("schema_version") == 1 and
            type(manifest.get("schema_version")) is int, "unsupported owner policy schema")
    require(manifest.get("network") == ALLOWED_NETWORK,
            "candidate must never masquerade as live mainnet")
    require(manifest.get("owner_legal_entity") == "Privi World Corp",
            "Privi World Corp must be the only designated network operator")
    require(manifest.get("owner_founder") == "Dario Canoy", "incorrect named founder")
    require(manifest.get("operator") == "Privi World Corp",
            "Privi World Corp must be the validator operator")
    require(manifest.get("governance_model") == "single-operator-permissioned",
            "centralized permissioned governance must be disclosed")
    require(type(manifest.get("independent_operator_count")) is int and
            manifest["independent_operator_count"] == 1,
            "no unauthorized additional operator")
    require(type(manifest.get("validator_operator_count")) is int and
            manifest["validator_operator_count"] == 1,
            "four validator signers do not constitute additional platform owners")

    for role in EXPECTED_ROLE_KEYS:
        value = manifest.get(role)
        require(isinstance(value, str) and HEX_ADDRESS.fullmatch(value) is not None and
                value.lower() == FOUNDER_WALLET.lower(),
                role + " must equal founder's public EVM wallet only")
    require(manifest.get("administrator_wallets") == [FOUNDER_WALLET],
            "administration wallet list must contain only the founder address")
    for role in ("recovery_guardians", "multisig_owners", "delegate_administrators"):
        require(manifest.get(role) == [],
                "unapproved admin authority: " + role)

    require(manifest.get("proposed_native_symbol") == "PRVI",
            "expected proposed native PRVI (not BNB PRIV or TEST)")
    require(type(manifest.get("proposed_max_supply_whole_prvi")) is int and
            manifest["proposed_max_supply_whole_prvi"] == 1_000_000_000,
            "native lifetime cap target must be 1B PRVI")
    require(manifest.get("third_party_token_bridges") is False,
            "no native PRVI bridge/pairing substitute")
    require(manifest.get("startup_consensus") ==
            "Point of Position REQUIRED NOT IMPLEMENTED",
            "existing Cosmos EVM must not be relabeled native Point of Position")
    require(manifest.get("real_prvi_issuance_enabled") is False,
            "financial issuance must remain disabled")
    require(manifest.get("financial_launch_enabled") is False,
            "mainnet launch must remain disabled pending verified release")
    require(manifest.get("signed_genesis_sha256") == "UNASSIGNED" and
            manifest.get("native_pop_release_sha256") == "UNASSIGNED",
            "candidate must not pretend to have signed production artifacts")
    require(manifest.get("production_validator_attestations") == "UNASSIGNED",
            "candidate must not claim actual PoP production validator attestations")
    require(manifest.get("status") == "DRAFT_ONLY_NOT_LIVE",
            "owner policy must explicitly remain non-live")
    return errors


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("--mode", choices=("draft", "launch"), required=True)
    args = p.parse_args()
    try:
        data = load_strict_json(args.manifest)
        errors = assess(data)
    except (ValueError, OSError, UnicodeError) as exc:
        print("NO-GO: owner manifest invalid or unsafe: " + type(exc).__name__,
              file=sys.stderr)
        return 3
    for error in errors:
        print("NO-GO: " + error, file=sys.stderr)
    if args.mode == "launch":
        print("NO-GO: sole wallet policy cannot authorize live financial mainnet. "
              "PoP consensus, bank issuance, signed genesis, validator host and "
              "independent audit gates remain unsatisfied.", file=sys.stderr)
        return 3
    if errors:
        return 3
    print("DRAFT_OWNER_POLICY_PASS: founder is sole proposed governance wallet. "
          "No mainnet deployed, minted or authorized.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
