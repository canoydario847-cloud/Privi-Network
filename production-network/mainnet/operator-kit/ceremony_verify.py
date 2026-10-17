#!/usr/bin/env python3
"""Cryptographically verify seven independent operator Ed25519 genesis attestations.

Never generates/handles private keys, creates genesis, deploys nodes or
activates financial mainnet. Signatures prove key possession, NOT ownership.
Requires the 'cryptography' package for RFC 8032 verification.
"""
import argparse
import json
from pathlib import Path
import re
import sys

HASH = re.compile(r"^[0-9a-f]{64}$")
COSMOS = re.compile(r"^privi-[a-z0-9-]{5,55}$")
BAD_EVM = {1, 56, 97, 4221, 262144, 31337, 1337, 999991}


def check_release(release):
    if not isinstance(release, dict):
        raise ValueError("release must be an object")
    expected = ("cosmos_chain_id", "evm_chain_id",
                "canonical_genesis_sha256", "binary_sha256", "allocations_sha256")
    if any(k not in release for k in expected):
        raise ValueError("reviewed release IDs and three SHA256 artifact digests required")
    if not isinstance(release["cosmos_chain_id"], str) or not COSMOS.fullmatch(release["cosmos_chain_id"]) or release["cosmos_chain_id"] == "privi-ci-nonproduction-999":
        raise ValueError("unreviewed Cosmos chain ID")
    eid = release["evm_chain_id"]
    if type(eid) is not int or eid < 1000 or eid in BAD_EVM or eid > 4294967295:
        raise ValueError("unreviewed or demo EVM numeric chain ID")
    for k in ("canonical_genesis_sha256", "binary_sha256", "allocations_sha256"):
        if not isinstance(release[k], str) or not HASH.fullmatch(release[k]) or release[k] == "0"*64:
            raise ValueError(f"real 32-byte lowercase artifact digest required: {k}")
    return {key: release[key] for key in expected}


def canonical_payload(release, operator_id, consensus_pubkey):
    data = check_release(release)
    if not isinstance(operator_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{3,100}", operator_id):
        raise ValueError("valid operator_id required")
    if not isinstance(consensus_pubkey, str) or not HASH.fullmatch(consensus_pubkey):
        raise ValueError("32-byte public consensus key as lowercase hex required")
    payload = {"domain": "PRIVI-MAINNET-RELEASE-ATTESTATION-v1",
               "operator_id": operator_id, "consensus_pubkey": consensus_pubkey, **data}
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def verify_release(release, operator_roster, attestations):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    check_release(release)
    rows = operator_roster.get("operators") if isinstance(operator_roster, dict) else None
    if not isinstance(rows, list) or len(rows) < 7:
        raise ValueError("seven independently reviewed operators are required")
    roster = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("malformed operator row")
        op = row.get("operator_id")
        pub = row.get("consensus_pubkey")
        if not isinstance(op, str) or not isinstance(pub, str):
            raise ValueError("operator record missing public identity")
        if op in roster:
            raise ValueError("duplicate operator ID")
        roster[op] = pub
    items = attestations.get("attestations") if isinstance(attestations, dict) else None
    if not isinstance(items, list) or len(items) != len(rows):
        raise ValueError("one signed release attestation is required per operator")
    seen_ops, seen_keys = set(), set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("malformed signed attestation")
        op = item.get("operator_id")
        consensus = item.get("consensus_pubkey")
        public = item.get("attestation_public_key")
        signature = item.get("signature")
        if op not in roster or op in seen_ops:
            raise ValueError("unknown or duplicate operator attestation")
        if not isinstance(consensus, str) or consensus != roster[op]:
            raise ValueError(f"{op}: consensus public key does not match reviewed roster")
        if not isinstance(public, str) or not HASH.fullmatch(public) or public in seen_keys:
            raise ValueError(f"{op}: duplicate or invalid Ed25519 attestation public key")
        if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{128}", signature):
            raise ValueError(f"{op}: invalid Ed25519 signature encoding")
        message = canonical_payload(release, op, consensus)
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(public)).verify(
                bytes.fromhex(signature), message)
        except (InvalidSignature, ValueError) as exc:
            raise ValueError(f"{op}: release attestation signature invalid") from exc
        seen_ops.add(op)
        seen_keys.add(public)
    if seen_ops != set(roster):
        raise ValueError("missing operator signature")
    return {"valid_operator_signatures": len(seen_ops),
            "status": "SIGNATURES_VALID_OWNERSHIP_AND_RELEASE_STILL_REQUIRE_EXTERNAL_APPROVAL"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--release", type=Path, required=True,
                   help="Unsigned reviewed digest/ID object; public metadata only")
    p.add_argument("--operator-id", help="Generate signing payload for one operator")
    p.add_argument("--consensus-pubkey", help="Public consensus key, lowercase hex")
    p.add_argument("--write-signing-payload", type=Path, help="Create immutable message file to sign offline")
    p.add_argument("--roster", type=Path)
    p.add_argument("--attestations", type=Path, help="Signed public release attestations")
    a = p.parse_args()
    try:
        release = json.loads(a.release.read_text(encoding="utf-8"))
        if a.write_signing_payload:
            if a.operator_id is None or a.consensus_pubkey is None:
                raise ValueError("operator-id and public consensus key required to create signing payload")
            with a.write_signing_payload.open("xb") as f:
                f.write(canonical_payload(release, a.operator_id, a.consensus_pubkey))
            print("Public signing payload saved. Operator must sign OFFLINE; never submit private keys.")
        else:
            if not a.roster or not a.attestations:
                raise ValueError("public roster and signed attestations required to verify")
            print(json.dumps(verify_release(
                release, json.loads(a.roster.read_text(encoding="utf-8")),
                json.loads(a.attestations.read_text(encoding="utf-8"))), indent=2))
        return 0
    except (OSError, ValueError, ImportError, TypeError) as exc:
        print("GENESIS SIGNATURE REVIEW BLOCKED:", str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
