#!/usr/bin/env python3
"""Offline PRVI launch evidence verifier. Does not launch nodes, generate coins, or sign genesis."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

CAP = 1_000_000_000
HEX64 = re.compile(r"^[a-fA-F0-9]{64}$")

def assess(manifest, genesis_path):
    errors = []
    def require(ok, why):
        if not ok:
            errors.append(why)
    require(manifest.get("network") == "privi-mainnet", "network must be privi-mainnet")
    require(manifest.get("symbol") == "PRVI", "symbol must be PRVI")
    require(manifest.get("test_assets_separate") is True, "TEST must be identified as separate and valueless")
    require(manifest.get("bnb_priv_separate") is True, "BNB PRIV must be identified as separate")
    supply = manifest.get("max_supply_whole_prvi")
    require(type(supply) is int and supply == CAP, "PRVI max supply must be exactly 1000000000")
    chain_id = manifest.get("cosmos_chain_id")
    require(isinstance(chain_id, str) and bool(chain_id.strip()) and chain_id != "local-4221", "unique mainnet Cosmos chain ID required")
    evm_id = manifest.get("evm_chain_id")
    require(type(evm_id) is int and evm_id > 0 and evm_id not in (1, 56, 97, 1337, 31337, 4221, 262144), "independently selected EVM chain ID required; common public/developer IDs are not approved")
    denom = manifest.get("base_denom")
    require(isinstance(denom, str) and bool(re.fullmatch(r"[a-z][a-z0-9/]{2,63}", denom)) and denom not in ("atest", "test", "stake", "aphotino"), "valid non-developer native PRVI base denomination required")
    validators = manifest.get("validators", [])
    require(isinstance(validators, list) and len(validators) >= 4, "at least four validators required")
    if isinstance(validators, list):
        # Reject malformed entries before inspecting attributes; never allow
        # untrusted evidence JSON to crash verification with TypeError.
        require(all(isinstance(v, dict) for v in validators),
                "each validator must be a JSON object")
        for attr in ("operator_id", "consensus_pubkey", "fault_domain"):
            values = [v.get(attr) for v in validators if isinstance(v, dict)]
            require(len(values) == len(validators) and all(isinstance(x, str) and x.strip() for x in values) and len(set(values)) == len(values),
                    "validator " + attr + " must be present and unique")
        require(all(isinstance(v, dict) and v.get("independent_operator_attestation") is True for v in validators),
                "each operator must explicitly attest independent control")
    sha = manifest.get("genesis_sha256")
    require(isinstance(sha, str) and HEX64.fullmatch(sha) is not None, "genesis_sha256 required")
    # Avoid unbounded memory consumption from a malformed or hostile genesis.
    # The verifier is an offline evidence tool, not a streaming parser.
    MAX_GENESIS_BYTES = 64 * 1024 * 1024
    if genesis_path.is_file() and genesis_path.stat().st_size > MAX_GENESIS_BYTES:
        errors.append("genesis exceeds 64 MiB offline audit limit")
        return errors
    require(genesis_path.is_file(), "genesis file missing")
    if genesis_path.is_file():
        actual = hashlib.sha256(genesis_path.read_bytes()).hexdigest()
        require(isinstance(sha, str) and actual.lower() == sha.lower(), "genesis SHA-256 mismatch")
        try:
            genesis = json.loads(genesis_path.read_text())
            require(isinstance(genesis, dict) and genesis.get("chain_id") == chain_id, "genesis chain_id mismatch")
            # Confirm only INITIAL supply: ongoing mint/issuance cap enforcement
            # still needs audited custom chain logic and external sign-off.
            if isinstance(chain_id, str) and isinstance(denom, str):
                from genesis_supply_audit import audit as audit_genesis_bank
                try:
                    audit_genesis_bank(genesis, denom, chain_id)
                except (ValueError, AttributeError, TypeError) as exc:
                    errors.append("initial PRVI bank supply audit: " + str(exc))
            else:
                errors.append("initial PRVI bank supply cannot be audited without a valid chain ID and denomination")
            errors.append("ongoing issuance cap, staking and vesting require independent audited chain-specific verification")
        except (ValueError, UnicodeError):
            errors.append("genesis must be valid UTF-8 JSON")
    for key in ("binary_sha256", "security_audit_url", "public_testnet_evidence_url", "incident_runbook_url", "signoff_record_url"):
        require(bool(manifest.get(key)), key + " evidence missing")
    # Offline declarations cannot demonstrate network health or cryptographic signatures.
    errors.append("independent validator signatures and live consensus checks must be externally verified")
    return errors

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True, type=Path, help="reviewed mainnet evidence JSON")
    p.add_argument("--genesis", required=True, type=Path, help="candidate unsigned/signed genesis JSON")
    args = p.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text())
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
        failures = assess(manifest, args.genesis)
    except (OSError, ValueError, UnicodeError) as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    for issue in failures:
        print("NO-GO: " + issue)
    print("NO-GO: offline review cannot authorize financial mainnet; see MAINNET_LAUNCH_GATE.md")
    return 1

if __name__ == "__main__":
    sys.exit(main())
