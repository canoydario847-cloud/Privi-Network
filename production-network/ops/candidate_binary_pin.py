#!/usr/bin/env python3
"""Verify a testnet-only candidate binary pin. Never authorizes mainnet.

Exit codes:
  0  pin matches the supplied binary and is explicitly non-production
  1  pin is well-formed but incomplete (UNPINNED sha) or hash mismatch / policy reject
  2  pin document cannot be loaded
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA = "privi-candidate-binary-pin-v1"
SCOPE = "testnet-candidate-only"
UPSTREAM_REPO = "cosmos/evm"
UPSTREAM_TAG = "v0.7.3"
UPSTREAM_COMMIT = "c3ae9067a7eadcdea55a5192226916deb44c71c4"
FORBIDDEN_CHAIN_IDS = frozenset({
    "local-4221",
    "privi",
    "privi-1",
    "privi-mainnet",
    "cosmoshub-4",
})
FORBIDDEN_EVM_IDS = frozenset({1, 56, 262144})
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TESTNET_CHAIN_RE = re.compile(r"^privi-testnet-[a-z0-9][a-z0-9-]{0,40}$")


def reject_duplicate_keys(pairs):
    record = {}
    for key, value in pairs:
        if key in record:
            raise ValueError(f"duplicate JSON key: {key}")
        record[key] = value
    return record


def load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    if not isinstance(data, dict):
        raise ValueError("pin must be a JSON object")
    return data


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_policy(pin: dict) -> list[str]:
    errors = []
    if pin.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if pin.get("scope") != SCOPE:
        errors.append(f"scope must be {SCOPE}")
    if pin.get("financial_mainnet") is not False:
        errors.append("financial_mainnet must be false")
    if pin.get("production_release") is not False:
        errors.append("production_release must be false")
    if pin.get("mainnet_activated") is not False:
        errors.append("mainnet_activated must be false")
    upstream = pin.get("upstream")
    if not isinstance(upstream, dict):
        errors.append("upstream object required")
    else:
        if upstream.get("repo") != UPSTREAM_REPO:
            errors.append(f"upstream.repo must be {UPSTREAM_REPO}")
        if upstream.get("tag") != UPSTREAM_TAG:
            errors.append(f"upstream.tag must be {UPSTREAM_TAG}")
        if upstream.get("commit") != UPSTREAM_COMMIT:
            errors.append("upstream.commit does not match pinned cosmos/evm v0.7.3")
    if pin.get("go") != "1.25.9":
        errors.append("go toolchain must be 1.25.9")
    if pin.get("sdk") != "v0.54.3":
        errors.append("sdk must be v0.54.3")
    chain = pin.get("cosmos_chain_id")
    if not isinstance(chain, str) or not TESTNET_CHAIN_RE.fullmatch(chain):
        errors.append("cosmos_chain_id must match privi-testnet-<name>")
    elif chain in FORBIDDEN_CHAIN_IDS:
        errors.append("cosmos_chain_id is a forbidden demo or mainnet id")
    evm = pin.get("evm_chain_id")
    if not isinstance(evm, int) or isinstance(evm, bool) or evm < 1:
        errors.append("evm_chain_id must be a positive integer")
    elif evm in FORBIDDEN_EVM_IDS:
        errors.append("evm_chain_id is a forbidden demo or public-mainnet id")
    artifact = pin.get("artifact")
    if not isinstance(artifact, dict):
        errors.append("artifact object required")
    else:
        if artifact.get("name") != "evmd":
            errors.append("artifact.name must be evmd")
        digest = artifact.get("sha256")
        if digest != "UNPINNED" and (not isinstance(digest, str) or not SHA_RE.fullmatch(digest)):
            errors.append("artifact.sha256 must be lowercase hex or UNPINNED")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", required=True, type=Path)
    parser.add_argument("--binary", type=Path, help="candidate evmd to hash")
    args = parser.parse_args(argv)
    try:
        pin = load(args.pin)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"PIN_UNREADABLE: {exc}")
        return 2
    errors = check_policy(pin)
    if errors:
        print("NO-GO: candidate binary pin rejected")
        for err in errors:
            print(f"- {err}")
        print("financial_mainnet_authorized=false")
        return 1
    digest = pin["artifact"]["sha256"]
    if digest == "UNPINNED":
        print("PIN_INCOMPLETE: artifact.sha256 is UNPINNED")
        print("financial_mainnet_authorized=false")
        print("production_release=false")
        return 1
    if args.binary is None:
        print("NO-GO: --binary is required when artifact.sha256 is set")
        print("financial_mainnet_authorized=false")
        return 1
    if not args.binary.is_file():
        print("NO-GO: binary path is not a file")
        print("financial_mainnet_authorized=false")
        return 1
    actual = sha256_file(args.binary)
    if actual != digest:
        print("NO-GO: binary SHA-256 does not match pin")
        print(f"expected={digest}")
        print(f"actual={actual}")
        print("financial_mainnet_authorized=false")
        return 1
    print("CANDIDATE_PIN_MATCH")
    print(f"sha256={actual}")
    print(f"cosmos_chain_id={pin['cosmos_chain_id']}")
    print(f"evm_chain_id={pin['evm_chain_id']}")
    print("scope=testnet-candidate-only")
    print("financial_mainnet_authorized=false")
    print("production_release=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
