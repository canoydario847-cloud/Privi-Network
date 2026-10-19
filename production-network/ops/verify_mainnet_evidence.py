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
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
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
    # Owner-selected architecture: FOUR distinct signing nodes controlled by
    # ONE operator (Privi World Corp). Do not demand or claim four independent
    # operator companies: this is a centrally operated, permissioned network.
    require(manifest.get("operator") == "Privi World Corp",
            "operator must be Privi World Corp")
    require(manifest.get("governance_model") == "single-operator-permissioned",
            "governance must disclose single-operator-permissioned control")
    require(type(manifest.get("independent_operator_count")) is int and
            manifest["independent_operator_count"] == 1,
            "independent_operator_count must be exactly 1")
    validators = manifest.get("validators")
    require(isinstance(validators, list) and len(validators) == 4,
            "exactly four separately keyed/hosted validators required")
    if isinstance(validators, list) and len(validators) == 4:
        identities = {f"privi-owner-val-{i:02d}" for i in range(1, 5)}
        ids = set()
        for idx, row in enumerate(validators):
            if not isinstance(row, dict):
                errors.append(f"validator[{idx}] must be an object")
                continue
            require(row.get("operator") == "Privi World Corp",
                    f"validator[{idx}] operator must be Privi World Corp")
            ident = row.get("id")
            if isinstance(ident, str):
                ids.add(ident)
            require(ident in identities, f"validator[{idx}] invalid id")
            require(type(row.get("voting_power_percent")) is int and
                    row["voting_power_percent"] == 25,
                    f"validator[{idx}] voting power must equal 25 percent")
            fpr = row.get("consensus_pubkey_sha256")
            require(isinstance(fpr, str) and HEX64.fullmatch(fpr) is not None,
                    f"validator[{idx}] consensus key fingerprint must be SHA-256 hex")
            evidence = row.get("signer_attestation")
            require(isinstance(evidence, str) and evidence.strip() not in ("", "UNASSIGNED"),
                    f"validator[{idx}] signer attestation reference missing")
        require(ids == identities, "validator IDs must be exactly 01-04 and unique")
        for attr in ("host_id", "fault_domain", "consensus_pubkey_sha256"):
            values = [row.get(attr) for row in validators if isinstance(row, dict)]
            require(len(values) == 4 and
                    all(isinstance(v, str) and bool(v.strip()) and v != "UNASSIGNED"
                        for v in values) and len(set(values)) == 4,
                    f"four distinct validator {attr} values required")
    sha = manifest.get("genesis_sha256")
    require(isinstance(sha, str) and HEX64.fullmatch(sha) is not None, "genesis_sha256 required")
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
            # Bank supply agreement does not prove native fee/staking/mint
            # configuration. Reject atest/stake fee masquerading as PRVI.
            try:
                from native_prvi_genesis_params import audit as audit_native_params
                audit_native_params(genesis)
            except (ValueError, TypeError, AttributeError) as exc:
                errors.append("native PRVI genesis parameter audit: " + str(exc))
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
