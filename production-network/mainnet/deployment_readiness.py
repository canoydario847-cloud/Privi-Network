#!/usr/bin/env python3
"""Privi FINANCIAL mainnet release-readiness verifier. NEVER deploys.

This is a fail-closed integration gate that cross-checks a reviewed binary,
canonical genesis, real allocations, operator roster, cryptographic signed
release attestations, and independent review manifest. It does NOT substitute
for independent human audits, beneficial-ownership verification or authorization.
It never opens ports, starts nodes, imports private keys or issues PRVI.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAP = str(10**27)
RELEASE_STATUS = "AUDITED_MAINNET_RELEASE_CANDIDATE"
TEST_CHAIN_IDS = {"local-4221", "local-privi-seven-4221", "privi-dev-1", "privi-ci-nonproduction-999"}


def mod(filename, name):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = mod("mainnet_preflight.py", "privi_release_preflight")
gencheck = mod("validate_candidate_genesis.py", "privi_release_gencheck")
operators = mod("independent_operator_roster.py", "privi_release_operators")
ceremony = mod("operator-kit/ceremony_verify.py", "privi_release_signatures")
genesis_binding = mod("genesis_operator_binding.py", "privi_release_genesis_operator_binding")


def check_consistency(manifest, config, release, roster):
    """Cross-check identities and invariants WITHOUT trusting any unverified claim."""
    errors = []
    if not all(isinstance(v, dict) for v in (manifest, config, release, roster)):
        return ["All four mainnet release input documents must be JSON objects"]
    network = config.get("network") or {}
    coin = config.get("coin") or {}
    mnet = manifest.get("network") or {}
    masset = manifest.get("asset") or {}
    mdistribution = manifest.get("distribution") or {}
    if config.get("status") != RELEASE_STATUS:
        errors.append("Mainnet source config is not an independently audited release candidate")
    if network.get("new_genesis_required") is not True or network.get("demo_genesis_reuse_permitted") is not False:
        errors.append("Clean mainnet genesis and refusal of testnet genesis re-use required")
    if (not isinstance(network.get("cosmos_chain_id"), str)
            or network["cosmos_chain_id"] in TEST_CHAIN_IDS
            or network["cosmos_chain_id"].startswith(("local-", "privi-dev"))):
        errors.append("Reviewed, distinct mainnet Cosmos chain ID required")
    if (type(network.get("evm_chain_id")) is not int
            or network.get("evm_chain_id") in {1,56,97,4221,262144,31337,1337,999991}):
        errors.append("Reviewed, distinct mainnet EVM chain ID required")
    if network.get("cosmos_chain_id") != mnet.get("cosmos_chain_id") or network.get("cosmos_chain_id") != release.get("cosmos_chain_id"):
        errors.append("Cosmos chain IDs must agree across config, manifest and signed release")
    if network.get("evm_chain_id") != mnet.get("evm_chain_id") or network.get("evm_chain_id") != release.get("evm_chain_id"):
        errors.append("EVM chain IDs must agree across config, manifest and signed release")
    if (coin.get("display_denom") != "PRVI" or coin.get("base_denom") != "aprvi"
            or coin.get("decimals") != 18 or coin.get("max_supply_base_units") != CAP
            or coin.get("inflation_enabled") is not False or coin.get("mint_module_begin_block_enabled") is not False
            or coin.get("checked_supply_cap_in_app") is not True):
        errors.append("Application source config must retain PRVI fixed-cap and disabled mint settings")
    if (masset.get("symbol") != "PRVI" or masset.get("base_denom") != "aprvi"
            or masset.get("decimals") != 18 or mdistribution.get("total_allocations_base_units") != CAP):
        errors.append("Manifest asset / allocation cap must match reviewed source config")
    for key, manifest_key in (("binary_sha256", "cosmos_evm_binary_sha256"),
                              ("canonical_genesis_sha256", "canonical_genesis_sha256")):
        if release.get(key) != mnet.get(manifest_key):
            errors.append(f"Release {key} differs from review manifest")
    if release.get("allocations_sha256") != mdistribution.get("allocations_sha256"):
        errors.append("Release allocation hash differs from review manifest")
    rows = roster.get("operators") or []
    vals = manifest.get("validators") or []
    if not isinstance(rows, list) or len(rows) < 7 or not isinstance(vals, list) or len(vals) != len(rows):
        errors.append("Same seven-or-more independent operators required in roster and manifest")
    else:
        by_id = {}
        for row in rows:
            if not isinstance(row, dict):
                errors.append("Malformed independent operator record")
                continue
            ident = row.get("operator_id")
            if ident in by_id:
                errors.append("Duplicate independent operator ID")
                continue
            by_id[ident] = row
        seen = set()
        for row in vals:
            if not isinstance(row, dict):
                errors.append("Malformed manifest validator record")
                continue
            ident = row.get("operator_id")
            if ident not in by_id or ident in seen:
                errors.append("Unknown or repeated manifest operator ID")
                continue
            seen.add(ident)
            source = by_id[ident]
            try:
                roster_key = operators.pubkey_bytes(source.get("consensus_pubkey"))
                manifest_key = operators.pubkey_bytes(row.get("consensus_pubkey"))
            except (ValueError, TypeError):
                roster_key = manifest_key = None
            if roster_key is None or manifest_key is None or roster_key != manifest_key:
                errors.append(f"Operator {ident}: consensus pubkey mismatch or malformed")
            if row.get("voting_power") != source.get("voting_power"):
                errors.append(f"Operator {ident}: voting power mismatches reviewed roster")
            if row.get("genesis_sha256") != release.get("canonical_genesis_sha256"):
                errors.append(f"Operator {ident}: must sign exact reviewed genesis hash")
        if set(by_id) != seen:
            errors.append("Every independent operator must occur in release manifest")
    return errors


def assess(manifest, config, genesis, allocations, binary, release, roster, attestations):
    errors = check_consistency(manifest, config, release, roster)
    try:
        errors += preflight.check_manifest(manifest, genesis, binary, allocations)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append("Review manifest / checksum validation failed: " + str(exc))
    try:
        genesis_document = json.loads(genesis.read_text(encoding="utf-8"))
        ledger_document = json.loads(allocations.read_text(encoding="utf-8"))
        errors += gencheck.errors_for(genesis_document, ledger_document, config)
        errors += genesis_binding.validate_binding(genesis_document, roster)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append("Reviewed full genesis and allocations required: " + str(exc))
    try:
        errors += operators.screen(roster)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append("Independent operator screening failed: " + str(exc))
    try:
        validated = ceremony.verify_release(release, roster, attestations)
        if validated.get("valid_operator_signatures") < 7:
            errors.append("Fewer than seven valid Ed25519 release signatures")
    except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        errors.append("Independent operator release attestations unverified: " + str(exc))
    return sorted(set(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "config", "genesis", "allocations", "binary",
                 "release", "roster", "attestations"):
        parser.add_argument("--" + name, required=True, type=Path)
    a = parser.parse_args()
    try:
        docs = [json.loads(getattr(a, n).read_text(encoding="utf-8"))
                for n in ("manifest", "config", "release", "roster", "attestations")]
        errors = assess(docs[0], docs[1], a.genesis, a.allocations, a.binary,
                        docs[2], docs[3], docs[4])
    except (OSError, ValueError, TypeError) as exc:
        errors = ["Missing or unreadable reviewed input: " + str(exc)]
    result = {"financial_mainnet_deployed": False,
              "status": "BLOCKED_NOT_DEPLOYED" if errors else "STATIC_PRECHECK_PASSED_ONLY",
              "blocking_requirements": errors,
              "independent_human_authorization_still_required": True,
              "source_isolation": "Do not use valueless TEST, BNB PRIV, or synthetic CI IDs"}
    print(json.dumps(result, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
