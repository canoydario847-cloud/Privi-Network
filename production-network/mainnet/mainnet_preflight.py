#!/usr/bin/env python3
"""Fail-closed, read-only Privi PRVI mainnet artifact readiness checks.

Never deploys, mints, signs, transfers, imports keys, or touches Railway.
Even when static checks pass, independent audits and operator verification
remain REQUIRED. See MAINNET_SPEC.md.
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

SUPPLY = 1_000_000_000 * 10**18
DEV_COSMOS_IDS = {"local-4221", "privi-dev-1", "local-privi-seven-4221", "privi-ci-nonproduction-999"}
DEV_EVM_IDS = {262144, 4221, 56, 97, 1, 31337, 1337, 999991}
SHA = re.compile(r"^[a-fA-F0-9]{64}$")
CHAIN = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1048576):
            digest.update(block)
    return digest.hexdigest()


def nonempty_https(value):
    if not isinstance(value, str):
        return False
    url = urlsplit(value)
    return url.scheme == "https" and bool(url.hostname) and not url.username and not url.password


def check_manifest(m, genesis=None, binary=None, allocations=None):
    errors = []

    def need(ok, why):
        if not ok:
            errors.append(why)

    def obj(parent, key):
        value = parent.get(key) if isinstance(parent, dict) else None
        if not isinstance(value, dict):
            errors.append(f"Missing section: {key}")
            return {}
        return value

    need(m.get("schema_version") == 1, "schema_version must be 1")
    need(m.get("status") == "READY_FOR_INDEPENDENT_REVIEW",
         "status must be READY_FOR_INDEPENDENT_REVIEW (never release authorization)")
    a = obj(m, "asset")
    need(a.get("symbol") == "PRVI", "Native ticker must be PRVI")
    need(str(a.get("max_supply")) == "1000000000", "PRVI supply cap must be 1,000,000,000")
    need(type(a.get("decimals")) is int and a["decimals"] == 18, "PRVI must use 18 decimals")
    need(a.get("base_denom") == "aprvi", "Native base denom must be aprvi")
    need(a.get("inflation_enabled") is False, "No unrestricted inflation is allowed under fixed cap")

    n = obj(m, "network")
    cid = n.get("cosmos_chain_id")
    eid = n.get("evm_chain_id")
    need(isinstance(cid, str) and bool(CHAIN.fullmatch(cid)) and cid not in DEV_COSMOS_IDS and not cid.startswith(("local-", "privi-dev")),
         "Unique non-demo Cosmos chain ID required")
    need(type(eid) is int and eid > 0 and eid not in DEV_EVM_IDS,
         "Unique non-demo EVM numeric chain ID required (with independent collision review)")
    need(n.get("upstream_development_genesis_reused") is False,
         "Upstream development genesis must never be reused")

    for field, supplied_path in (
        ("cosmos_evm_binary_sha256", binary),
        ("canonical_genesis_sha256", genesis),
    ):
        digest = n.get(field)
        need(isinstance(digest, str) and bool(SHA.fullmatch(digest)),
             f"Real verified SHA-256 required: network.{field}")
        if supplied_path is None:
            errors.append(f"Missing independently built artifact input for network.{field}")
        else:
            if not supplied_path.is_file():
                errors.append(f"Artifact not found: {supplied_path}")
            elif isinstance(digest, str) and SHA.fullmatch(digest):
                need(sha256_file(supplied_path) == digest.lower(), f"SHA-256 mismatch: {supplied_path}")

    d = obj(m, "distribution")
    need(d.get("total_allocations_base_units") == str(SUPPLY),
         "Allocations must equal EXACTLY 10^27 aprvi (1 billion PRVI)")
    dg = d.get("allocations_sha256")
    need(isinstance(dg, str) and bool(SHA.fullmatch(dg)),
         "Reviewed allocations manifest SHA-256 required")
    if allocations is None:
        errors.append("Missing actual allocations manifest artifact")
    elif not allocations.is_file():
        errors.append(f"Missing allocations manifest: {allocations}")
    elif isinstance(dg, str) and SHA.fullmatch(dg):
        need(sha256_file(allocations) == dg.lower(), "Allocations manifest SHA-256 mismatch")
        try:
            data = json.loads(allocations.read_text(encoding="utf8"))
            rows = data.get("allocations", []) if isinstance(data, dict) else None
            need(isinstance(rows, list) and len(rows) > 0, "Empty allocations manifest")
            if isinstance(rows, list):
                total = 0
                addrs = set()
                for i, row in enumerate(rows):
                    if not isinstance(row, dict):
                        errors.append(f"Allocation entry {i} is invalid")
                        continue
                    addr = row.get("address")
                    if not isinstance(addr, str) or not addr:
                        errors.append(f"Allocation entry {i} missing address")
                    elif addr in addrs:
                        errors.append(f"Duplicated allocation address: {addr}")
                    else:
                        addrs.add(addr)
                    value = row.get("amount_base_units")
                    if not isinstance(value, str) or not value.isdecimal() or int(value) <= 0:
                        errors.append(f"Invalid positive base units at allocation entry {i}")
                    else:
                        total += int(value)
                need(total == SUPPLY, "Actual allocation amounts do not sum to fixed PRVI cap")
        except (ValueError, OSError) as exc:
            errors.append(f"Allocations could not be parsed: {exc}")

    for field in ("public_vesting_schedule_url", "cap_invariant_audit_url"):
        need(nonempty_https(d.get(field)), f"Independent review evidence required: distribution.{field}")

    for section, fields in (
        ("assessments", ("chain_security_audit_url", "tokenomics_vesting_audit_url",
                         "independent_legal_review_url", "signed_release_approval_url")),
        ("resilience", ("independent_operator_review_url", "rpc_gateway_review_url",
                        "backup_and_double_sign_rehearsal_url",
                        "public_rehearsal_evidence_url",
                        "monitoring_and_incident_runbook_url")),
    ):
        values = obj(m, section)
        for field in fields:
            need(nonempty_https(values.get(field)), f"Required review evidence: {section}.{field}")

    vals = m.get("validators")
    need(isinstance(vals, list) and len(vals) >= 7,
         "At least seven independently controlled validator operators required")
    if isinstance(vals, list):
        operators = set()
        keyset = set()
        powers = []
        provider = set()
        region = set()
        for i, row in enumerate(vals):
            if not isinstance(row, dict):
                errors.append(f"Validator entry {i} is not an object")
                continue
            op = row.get("operator_id")
            pub = row.get("consensus_pubkey")
            need(isinstance(op, str) and bool(op.strip()) and op not in operators,
                 f"Validator {i}: unique operator_id missing/duplicated")
            need(isinstance(pub, str) and len(pub) >= 40 and pub not in keyset,
                 f"Validator {i}: unique public consensus key required")
            if isinstance(op, str):
                operators.add(op)
            if isinstance(pub, str):
                keyset.add(pub)
            power = row.get("voting_power")
            need(type(power) is int and power > 0, f"Validator {i}: positive integer voting_power required")
            if type(power) is int and power > 0:
                powers.append(power)
            provid = row.get("infrastructure_provider")
            geo = row.get("region")
            if isinstance(provid, str) and provid.strip():
                provider.add(provid)
            if isinstance(geo, str) and geo.strip():
                region.add(geo)
            need(row.get("genesis_sha256") == n.get("canonical_genesis_sha256"),
                 f"Validator {i}: expected genesis agreement is missing")
            need(nonempty_https(row.get("signed_operator_attestation_url")),
                 f"Validator {i}: independent operator signed attestation is missing")
        if len(powers) == len(vals) and powers:
            total = sum(powers)
            need(all(3 * power < total for power in powers),
                 "One validator controls at least 1/3 of initial voting power")
        need(len(provider) >= 3, "At least three independent infrastructure providers needed")
        need(len(region) >= 3, "At least three distinct failure regions needed")

    gates = obj(m, "launch_authorization")
    for field in ("genesis_ceremony_complete", "operators_verified",
                  "critical_findings_remediated", "manual_release_gate_open"):
        need(gates.get(field) is True, f"Independent release gate NOT passed: {field}")

    if genesis is not None and genesis.is_file():
        try:
            g = json.loads(genesis.read_text(encoding="utf8"))
            need(g.get("chain_id") == cid, "Genesis Cosmos chain ID mismatch")
            st = g.get("app_state") or {}
            bank = st.get("bank") or {}
            supply = bank.get("supply") or []
            native = sum(int(c.get("amount","0")) for c in supply if c.get("denom") == "aprvi")
            need(native == SUPPLY, "Genesis native bank supply not exactly fixed PRVI cap")
            balances = bank.get("balances") or []
            balsum = sum(int(c.get("amount","0")) for b in balances
                         for c in b.get("coins",[]) if c.get("denom") == "aprvi")
            need(balsum == native, "Genesis native balances don't reconcile with bank supply")
            need(((st.get("staking") or {}).get("params") or {}).get("bond_denom") == "aprvi",
                 "Native staking bond denomination must be aprvi")
            need(((st.get("evm") or {}).get("params") or {}).get("evm_denom") == "aprvi",
                 "Native EVM fee denomination must be aprvi")
        except (ValueError, TypeError, OSError, AttributeError, KeyError) as exc:
            errors.append(f"Genesis could not be verified: {exc}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--genesis", type=Path)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--allocations", type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf8"))
        if not isinstance(manifest, dict):
            raise ValueError("Manifest must be a JSON object")
    except (ValueError, OSError) as exc:
        print(f"MAINNET BLOCKED: invalid review manifest: {exc}", file=sys.stderr)
        return 2
    errors = check_manifest(manifest,args.genesis,args.binary,args.allocations)
    if errors:
        print(f"MAINNET BLOCKED ({len(errors)} unresolved release requirements):",file=sys.stderr)
        for err in errors:
            print(" - " + err, file=sys.stderr)
        return 1
    print("STATIC PREFLIGHT PASSED. MANUAL INDEPENDENT VERIFICATION STILL REQUIRED.")
    print("This script NEVER deploys, authorizes minting, or validates operator signatures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
