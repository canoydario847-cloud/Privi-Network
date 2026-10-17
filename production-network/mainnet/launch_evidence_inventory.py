#!/usr/bin/env python3
"""Build a PUBLIC, read-only Privi PRVI financial-mainnet evidence gap report.

No validator key, private genesis, credentials, balance, coin, RPC, mint, deploy
or release approval is created. Public input documents may contain *claims*
of real-world control; this report cannot establish that they are true. No
status returned by this utility opens the financial mainnet release gate.

Run with the committed templates to enumerate exactly what is still missing.
For proposed real inputs, use separate --config/--manifest/--roster/--release
and --attestations paths and --genesis/--allocations/--binary only after safe
external collection, real independent reviews and signer ceremonies.
Never upload confidential keys or custody documents to GitHub Actions.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
MAX_FILE = 4 * 1024 * 1024
CAP = "1000000000000000000000000000"
SAFE_STATUS = "BLOCKED_AWAITING_INDEPENDENT_PRODUCTION_EVIDENCE"


def module(path, alias):
    spec = importlib.util.spec_from_file_location(alias, HERE / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


operator_screen = module("independent_operator_roster.py", "prvi_inventory_operators")
ceremony = module("operator-kit/ceremony_verify.py", "prvi_inventory_ceremony")
genesis_check = module("validate_candidate_genesis.py", "prvi_inventory_genesis")
genesis_binding = module("genesis_operator_binding.py", "prvi_inventory_binding")
manifest_check = module("mainnet_preflight.py", "prvi_inventory_preflight")
release_consistency = module("deployment_readiness.py", "prvi_inventory_release")


def read_public_json(path):
    if path is None:
        return None
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ValueError("Evidence file missing, linked or larger than review safety limit")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("Input must be a public JSON object")
    return doc


def gate(key, *, structurally_passed, title, evidence_needed, diagnostics):
    # Do not copy raw source documents or operator private contact records
    # into reports or CI logs. Only limited generic verifier messages.
    clean = []
    for note in diagnostics[:5]:
        if isinstance(note, str):
            clean.append(note[:160])
    return {
        "key": key, "title": title,
        "status": "EVIDENCE_STRUCTURE_PRESENT_NOT_INDEPENDENTLY_VERIFIED"
                  if structurally_passed else "BLOCKED",
        "evidence_needed": evidence_needed,
        "verification_notes": clean,
    }


def safe_issues(check, *args, **kwargs):
    try:
        outcome = check(*args, **kwargs)
        return list(outcome) if outcome else []
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        return [type(exc).__name__ + ": " + str(exc)[:120]]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fp:
        while chunk := fp.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def report(config, manifest, roster, release, attestations, *,
           genesis=None, allocations=None, binary=None,
           genesis_path=None, allocations_path=None, binary_path=None):
    gates = []
    if not all(isinstance(x, dict) for x in (config, manifest, roster, release, attestations)):
        raise ValueError("Five public evidence documents required")

    net = config.get("network") or {}
    mnet = manifest.get("network") or {}
    chain_good = config.get("status") == "AUDITED_MAINNET_RELEASE_CANDIDATE"
    reasons = []
    try:
        ceremony.check_release(release)
    except (ValueError, TypeError, KeyError) as exc:
        reasons.append("Production release IDs and hashes are not finalized")
        chain_good = False
    else:
        if (net.get("cosmos_chain_id") != release.get("cosmos_chain_id")
            or net.get("evm_chain_id") != release.get("evm_chain_id")
            or mnet.get("cosmos_chain_id") != release.get("cosmos_chain_id")
            or mnet.get("evm_chain_id") != release.get("evm_chain_id")):
            chain_good = False
            reasons.append("Production Cosmos/EVM IDs do not match between reviewed records")
    if not chain_good and not reasons:
        reasons.append("Production source config status is still design-only or unreviewed")
    gates.append(gate(
        "ids_and_release", structurally_passed=chain_good,
        title="Independently reviewed production network IDs and release artifacts",
        evidence_needed="Registered mainnet Cosmos/EVM chain IDs, audited source config and immutable binary/genesis/ledger hashes",
        diagnostics=reasons))

    roster_issues = safe_issues(operator_screen.screen, roster)
    gates.append(gate(
        "seven_independent_operators", structurally_passed=not roster_issues,
        title="Seven genuinely independent validator ownership and custody records",
        evidence_needed="7+ independent real operators, keys, infrastructure/region evidence and third-party control review",
        diagnostics=roster_issues or ["Roster structure passes; ownership is not independently proven by this report"]))

    signature_issues = []
    try:
        signatures = ceremony.verify_release(release, roster, attestations)
        verified_sig_count = signatures.get("valid_operator_signatures", 0)
    except (ValueError, TypeError, KeyError, ImportError) as exc:
        verified_sig_count = 0
        signature_issues = ["Matching 7+ real operator signed release statements are unavailable or invalid"]
    gates.append(gate(
        "genesis_release_signatures", structurally_passed=verified_sig_count >= 7 and not roster_issues,
        title="Cryptographic operator agreement with immutable audited genesis/release",
        evidence_needed="Independently held operator keys, signed public release attestations, matching approved hashes",
        diagnostics=signature_issues or ["Ed25519 signatures verify; real signer control requires independent review"]))

    available = genesis is not None and allocations is not None and genesis_path is not None and allocations_path is not None
    genesis_issues = []
    if not available:
        genesis_issues.append("Missing final real-funded genesis.json or disclosed beneficiary allocation ledger")
    else:
        genesis_issues.extend(safe_issues(genesis_check.errors_for, genesis, allocations, config))
        genesis_issues.extend(safe_issues(genesis_binding.validate_binding, genesis, roster))
        hashes = (
            ("canonical_genesis_sha256", "canonical_genesis_sha256", genesis_path),
            ("allocations_sha256", "allocations_sha256", allocations_path)
        )
        for release_name, _, file_path in hashes:
            if release.get(release_name) != digest(file_path):
                genesis_issues.append("Reviewed " + release_name + " digest differs from actual artifact")
        if (release.get("canonical_genesis_sha256") != mnet.get("canonical_genesis_sha256")
             or release.get("allocations_sha256") != (manifest.get("distribution") or {}).get("allocations_sha256")):
            genesis_issues.append("Genesis or ledger hash differs between release and manifest")
    gates.append(gate(
        "audited_allocations_and_genesis", structurally_passed=available and not genesis_issues,
        title="Real 1B PRVI allocations, enforced vesting and 7-signer canonical genesis",
        evidence_needed="Real reviewed beneficiary ledger, funded canonical genesis, enforceable on-chain vesting and consensus-key binding",
        diagnostics=genesis_issues or ["Static genesis structure passes; Cosmos InitChain and beneficiary custody still require audit"]))

    full_inputs = available and binary_path is not None and binary is not None
    review_issues = []
    if not full_inputs:
        review_issues.append("Need reviewed binary, canonical genesis, and complete beneficiary allocation ledger")
    else:
        review_issues.extend(safe_issues(
            manifest_check.check_manifest, manifest,
            genesis=Path(genesis_path), allocations=Path(allocations_path), binary=Path(binary_path)))
        if digest(binary_path) != release.get("binary_sha256"):
            review_issues.append("Actual independently reviewed binary SHA-256 differs from release")
        review_issues.extend(safe_issues(release_consistency.check_consistency, manifest, config, release, roster))
    gates.append(gate(
        "independent_reviews_and_binary", structurally_passed=full_inputs and not review_issues,
        title="Matching audited binary, external chain/tokenomics/legal review and operational evidence",
        evidence_needed="Reproducible production build, independent audited documents, resilience/drills, legal scope and signed release",
        diagnostics=review_issues or ["Referenced review metadata passes static checks; URLs and audit scope require external verification"]))

    auth = manifest.get("launch_authorization") or {}
    auth_claims = (
        auth.get("genesis_ceremony_complete") is True
        and auth.get("operators_verified") is True
        and auth.get("critical_findings_remediated") is True
        and auth.get("manual_release_gate_open") is True
    )
    gates.append(gate(
        "final_manual_authorization", structurally_passed=False,
        title="Separate human review, independently verified authorizations and controlled production launch",
        evidence_needed="External signer and auditor identity validation, governance/legal scope, incident plans and authorized final go/no-go",
        diagnostics=[
            "All release approvals must be independently authenticated; this tool never opens the launch gate"
            if auth_claims else
            "One or more explicit final launch-authorization flags remain false or absent",
        ]))

    return {
        "schema_version": 1,
        "project": "Privi native financial mainnet",
        "financial_mainnet_status": "NOT_ACTIVATED",
        "release_decision": "NO_GO",
        "status": SAFE_STATUS,
        "production_operator_count": len(roster.get("operators") or []) if isinstance(roster.get("operators"), list) else 0,
        "cryptographically_verified_release_signature_count": verified_sig_count,
        "audited_genesis_supplied": available,
        "manual_deployment_authorized_by_this_report": False,
        "no_real_coins_minted_or_deployed_by_this_report": True,
        "self_reported_approvals_are_not_independent_evidence": True,
        "gates": gates,
        "limitations": "All document references and ownership claims require independent off-platform verification. Passing static checks is NOT launch approval."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "privi_chain_config.json")
    parser.add_argument("--manifest", type=Path, default=HERE / "manifest.example.json")
    parser.add_argument("--roster", type=Path, default=HERE / "operator_roster.template.json")
    parser.add_argument("--release", type=Path, default=HERE / "operator-kit/release.template.json")
    parser.add_argument("--attestations", type=Path, default=HERE / "operator-kit/attestations.template.json")
    parser.add_argument("--genesis", type=Path)
    parser.add_argument("--allocations", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-no-go", action="store_true")
    args = parser.parse_args()
    try:
        source = {name: read_public_json(getattr(args, name))
                  for name in ("config", "manifest", "roster", "release", "attestations")}
        genesis = read_public_json(args.genesis)
        allocations = read_public_json(args.allocations)
        if args.output.exists():
            raise ValueError("Refusing to overwrite existing evidence report")
        if args.binary is not None and (not args.binary.is_file() or args.binary.is_symlink()):
            raise ValueError("Binary input not a regular file")
        result = report(**source, genesis=genesis, allocations=allocations,
                        binary=args.binary, genesis_path=args.genesis,
                        allocations_path=args.allocations, binary_path=args.binary)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("Financial PRVI mainnet: " + result["release_decision"])
        for row in result["gates"]:
            print(" - " + row["key"] + ": " + row["status"])
        if not args.expect_no_go:
            print("NOT a launch approval. Machine-readable details: " + str(args.output))
            return 2
        return 0 if result["release_decision"] == "NO_GO" else 1
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(1, "EVIDENCE REVIEW BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
