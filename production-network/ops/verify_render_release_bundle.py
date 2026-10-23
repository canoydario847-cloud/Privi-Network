#!/usr/bin/env python3
"""Verify an exact Privi unsigned-test release bundle, without executing it.

This is NOT an authorization to deploy, sign, sell, or issue PRVI.
A production binary requires separate independent audit, signed attestation,
key custody, chain state and 4-host consensus proofs. We NEVER start a node.
"""
import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path

PINNED_UPSTREAM = "c3ae9067a7eadcdea55a5192226916deb44c71c4"
REVIEW_BINARY = "privi-evmd-UNSIGNED-TEST-ONLY"
MAX_BINARY = 512 * 1024 * 1024
MAX_GENESIS = 32 * 1024 * 1024
MAX_METADATA = 64 * 1024
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
COSMOS_ID = re.compile(r"^privi-[a-z0-9-]{3,60}-[1-9][0-9]*$")


class UnsafeRelease(ValueError):
    pass


def unique_pairs(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise UnsafeRelease("duplicate JSON property in release manifest/genesis")
        d[k] = v
    return d


def read_regular(path, limit):
    """Reject links, pipes, devices, excessive size and empty files."""
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode) or not (0 < st.st_size <= limit):
        raise UnsafeRelease("release input must be a nonempty bounded regular file")
    # lstat prevents following a file symlink; compare inode after opening.
    with open(path, "rb") as f:
        if os.fstat(f.fileno()).st_ino != st.st_ino:
            raise UnsafeRelease("release input changed during inspection")
        value = f.read(limit + 1)
    if not value or len(value) > limit:
        raise UnsafeRelease("release input exceeds size limit")
    return value


def read_json(path, limit):
    raw = read_regular(path, limit)
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              UnsafeRelease("nonfinite JSON value forbidden")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UnsafeRelease("malformed UTF-8 release JSON") from exc


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise UnsafeRelease(message)


def parse_provenance(raw):
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise UnsafeRelease("invalid build provenance encoding") from exc
    expected = {"privi_source_commit", "upstream_cosmos_evm_tag", "upstream_cosmos_evm_commit"}
    result = {}
    for line in lines:
        if "=" not in line:
            raise UnsafeRelease("invalid provenance line")
        k, v = line.split("=", 1)
        if k not in expected or k in result or not v or v.strip() != v:
            raise UnsafeRelease("unknown, missing or duplicated provenance field")
        result[k] = v
    require(set(result) == expected, "incomplete build provenance")
    require(result["upstream_cosmos_evm_tag"] == "v0.7.3", "upstream Cosmos EVM tag changed")
    require(result["upstream_cosmos_evm_commit"] == PINNED_UPSTREAM,
            "upstream Cosmos EVM commit changed")
    require(bool(HEX40.fullmatch(result["privi_source_commit"])),
            "invalid Git commit in provenance")
    return result


def validate_manifest(manifest):
    fields = {
        "schema_version", "stage", "operator", "node_binary_sha256", "genesis_sha256",
        "privi_source_commit", "cosmos_chain_id", "evm_chain_id", "native_denom",
        "financial_launch_enabled", "production_ready", "validator_service_id",
    }
    require(isinstance(manifest, dict) and set(manifest) == fields,
            "release manifest missing/unknown fields (secrets must not be embedded)")
    fixed = {
        "schema_version": 1,
        "stage": "UNSIGNED_CI_REVIEW_ONLY",
        "operator": "Privi World Corp",
        "native_denom": "aprvi",
        "financial_launch_enabled": False,
        "production_ready": False,
        "validator_service_id": "UNASSIGNED",
    }
    for k, v in fixed.items():
        require(type(manifest.get(k)) is type(v) and manifest[k] == v,
                f"{k}: financial launch or credential/identity substitution denied")
    for k in ("node_binary_sha256", "genesis_sha256"):
        require(isinstance(manifest[k], str) and bool(HEX64.fullmatch(manifest[k])),
                f"{k}: a concrete lowercase SHA-256 digest is required")
    require(isinstance(manifest["privi_source_commit"], str) and
            bool(HEX40.fullmatch(manifest["privi_source_commit"])),
            "source commit must be exact 40-character lowercase Git ID")
    require(isinstance(manifest["cosmos_chain_id"], str) and
            bool(COSMOS_ID.fullmatch(manifest["cosmos_chain_id"])) and
            "mainnet" not in manifest["cosmos_chain_id"],
            "unsigned release must use a uniquely identified valueless Privi test chain")
    eid = manifest["evm_chain_id"]
    require(type(eid) is int and 0 < eid <= 2**64 - 1 and eid not in
            (1, 56, 97, 1337, 31337, 4221, 262144),
            "test chain must use a distinct numeric EVM chain ID")


def parse_sums(raw):
    """Require exactly the official four artifact hashes, no alternate paths."""
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise UnsafeRelease("non-ASCII sha256 sums") from exc
    expected = {REVIEW_BINARY, "GO-BUILD-INFO.txt", "BUILD-PROVENANCE.txt", "READ-ME-FIRST.txt"}
    seen = {}
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match:
            raise UnsafeRelease("malformed SHA256SUMS entry or path traversal")
        digest, filename = match.groups()
        if filename not in expected or filename in seen:
            raise UnsafeRelease("unapproved or duplicate SHA256SUMS entry")
        seen[filename] = digest
    require(set(seen) == expected, "unsigned CI artifact is incomplete")
    return seen


def verify(bundle_dir, genesis_path, manifest_path):
    """Return hash evidence only; never execute, deploy or declare GO."""
    manifest = read_json(manifest_path, MAX_METADATA)
    validate_manifest(manifest)
    root = Path(bundle_dir)
    require(root.is_dir() and not root.is_symlink(), "bundle must be a real directory")
    sums = parse_sums(read_regular(root / "SHA256SUMS", MAX_METADATA))
    parts = {name: read_regular(root / name, MAX_BINARY if name == REVIEW_BINARY
                                else MAX_METADATA) for name in sums}
    for name, payload in parts.items():
        require(sha256(payload) == sums[name], "CI bundle checksum mismatch: " + name)
    require(sha256(parts[REVIEW_BINARY]) == manifest["node_binary_sha256"],
            "binary differs from exact approved CI hash")
    require(b"UNSIGNED" in parts["READ-ME-FIRST.txt"] and
            b"NOT A PRODUCTION RELEASE" in parts["READ-ME-FIRST.txt"],
            "unsigned binary warning absent or modified")
    prov = parse_provenance(parts["BUILD-PROVENANCE.txt"])
    require(prov["privi_source_commit"] == manifest["privi_source_commit"],
            "bundle source commit differs from declared source revision")
    genesis_raw = read_regular(genesis_path, MAX_GENESIS)
    require(sha256(genesis_raw) == manifest["genesis_sha256"],
            "genesis does not match candidate hash")
    genesis = read_json(genesis_path, MAX_GENESIS)
    require(isinstance(genesis, dict) and genesis.get("chain_id") ==
            manifest["cosmos_chain_id"], "genesis chain identity mismatch")
    require(isinstance(genesis.get("app_state"), dict),
            "genesis must carry application state")
    return {
        "result": "UNSIGNED_TEST_RELEASE_HASHES_MATCHED_NONLIVE",
        "source_commit": prov["privi_source_commit"],
        "binary_sha256": manifest["node_binary_sha256"],
        "genesis_sha256": manifest["genesis_sha256"],
        "cosmos_chain_id": manifest["cosmos_chain_id"],
        "financial_launch": "NO_GO",
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--genesis", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        result = verify(a.bundle, a.genesis, a.manifest)
    except (OSError, ValueError) as exc:
        print("RELEASE CHECK FAILED:", str(exc))
        return 2
    print(json.dumps(result, sort_keys=True))
    print("NONLIVE EVIDENCE ONLY: production validators and PRVI issuance remain blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
