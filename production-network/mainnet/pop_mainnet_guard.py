#!/usr/bin/env python3
"""Fail-closed Privi mainnet gate for Point of Position (PoP) consensus.

Build and test data-layer PoP now. Financial mainnet is NOT activated.
No automatic approval from JSON fields or owner/self-attested claims.
"""
import argparse
import json
from pathlib import Path

REQUIRED_IOT_CONTROLS = frozenset({
    "native_privi_only",
    "developer_registry",
    "enterprise_company_registry",
    "company_authorized_gateway",
    "company_suspension_enforced",
    "independent_company_admin_handover",
    "revoke_prior_company_gateway_epoch",
    "device_enrollment",
    "ed25519_gateway_auth",
    "sequence_replay_protection",
    "pop_company_zone_sequence_commitment",
    "receipt_and_genesis_verification",
    "local_ai_metadata_minimization",
    "no_external_bridge_or_pairing",
    "no_automatic_prvi_mint",
})

# The current 0.7.3 Cosmos EVM stack has not been replaced with a separately
# reviewed, position-based BFT voter / proposer / finality implementation.
POP_CONSENSUS_IMPLEMENTED = False
NATIVE_FINANCIAL_RELEASE_AUDITED = False


def gate(manifest: dict, *, financial_mainnet: bool = True) -> dict:
    """Describe blockers without enabling chain state, funds, or deployment."""
    blockers = []
    if not isinstance(manifest, dict):
        return {"status": "NO_GO", "blockers": ["Invalid mainnet manifest"]}
    if manifest.get("chain_family") != "privi-native":
        blockers.append("Native Privi chain identity required")
    if manifest.get("target_protocol") != "Point of Position":
        blockers.append("Point of Position must be explicitly named")
    if manifest.get("consensus_kind") in ("pos", "posa", "proof-of-stake", "proof-of-staked-authority"):
        blockers.append("PoS or PoSA cannot be represented as Point of Position")
    if manifest.get("iot_settlement") != "privi-only":
        blockers.append("IoT commitments must settle on Privi only")
    if manifest.get("external_bridges") is not False or manifest.get("external_pairings") is not False:
        blockers.append("External bridges and automatic token pairings must be disabled")
    if manifest.get("real_prvi_rewards") is not False:
        blockers.append("No automatic spendable PRVI data rewards permitted")
    controls = manifest.get("iot_controls")
    if not isinstance(controls, dict):
        blockers.append("IoT integration controls evidence missing")
    else:
        for name in sorted(REQUIRED_IOT_CONTROLS):
            if controls.get(name) is not True:
                blockers.append("IoT control not evidenced: " + name)
    if financial_mainnet:
        if not POP_CONSENSUS_IMPLEMENTED:
            blockers.append("Independent PoP BFT consensus engine not implemented or audited")
        if not NATIVE_FINANCIAL_RELEASE_AUDITED:
            blockers.append("Native PRVI cap, SDK bank bypasses and release not independently audited")
        blockers.append("No verified independent PoP validator deployment or public finality proof")
    return {"status": "NO_GO" if blockers else "DEVELOPMENT_ONLY",
            "production_mainnet_activated": False,
            "financial_prvi_issued": False,
            "blockers": blockers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--development", action="store_true",
                        help="evaluate development controls only; no production authorization")
    args = parser.parse_args()
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = gate(data, financial_mainnet=not args.development)
    except (OSError, ValueError) as exc:
        result = {"status": "NO_GO", "production_mainnet_activated": False,
                  "blockers": ["Manifest not available or invalid: " + type(exc).__name__]}
    print(json.dumps(result, indent=2))
    # A nonfinancial development check may pass offline, but mainnet NEVER
    # proceeds until a new audited version intentionally replaces this gate.
    raise SystemExit(0 if args.development and not result["blockers"] else 3)


if __name__ == "__main__":
    main()
