#!/usr/bin/env python3
"""Produce a hash-only CI candidate build receipt; never publish an executable.

This deliberately accepts ONLY the synthetic build IDs from GitHub CI.
The artifact is NOT an audited PRVI mainnet release, genesis or launch gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

PIN = "c3ae9067a7eadcdea55a5192226916deb44c71c4"
CI_COSMOS = "privi-ci-nonproduction-999"
CI_EVM = 999991
CAP = str(10**27)


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for data in iter(lambda: fh.read(1024*1024), b""):
            hasher.update(data)
    return hasher.hexdigest()


def make_receipt(binary, patch, config, *, ref, commit, go_version):
    binary, patch, config = map(Path, (binary, patch, config))
    doc = json.loads(config.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("candidate config must be a JSON object")
    if doc.get("status") != "DESIGN_ONLY_NOT_A_GENESIS":
        raise ValueError("production or unapproved source config blocked")
    if doc.get("network", {}).get("cosmos_chain_id") != CI_COSMOS:
        raise ValueError("ONLY the synthetic Cosmos CI chain ID is permitted")
    if doc["network"].get("evm_chain_id") != CI_EVM:
        raise ValueError("ONLY the synthetic EVM CI chain ID is permitted")
    if doc.get("source", {}).get("commit") != PIN:
        raise ValueError("upstream not pinned to audited review target")
    coin = doc.get("coin", {})
    if (coin.get("display_denom"), coin.get("base_denom"), coin.get("decimals"),
        coin.get("max_supply_base_units"), coin.get("inflation_enabled"),
        coin.get("mint_module_begin_block_enabled")) != (
        "PRVI", "aprvi", 18, CAP, False, False):
        raise ValueError("PRVI candidate settings are not fixed-cap design")
    if doc.get("constraints", {}).get("no_mainnet_deploy_or_mint") is not True:
        raise ValueError("deployment prohibition must be explicit")
    if not isinstance(ref, str) or not ref.startswith("refs/pull/"):
        raise ValueError("receipt must originate from a pull-request CI ref")
    if not isinstance(commit, str) or re.fullmatch(r"[a-fA-F0-9]{40}", commit) is None:
        raise ValueError("complete Git commit SHA required")
    if not isinstance(go_version, str) or not go_version.startswith("go version go1.25.9 "):
        raise ValueError("Go toolchain must be pinned")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("binary is missing or nonexecutable")
    with binary.open("rb") as fp:
        if fp.read(4) != b"\x7fELF":
            raise ValueError("Linux ELF binary expected")
    if not patch.is_file() or patch.stat().st_size == 0:
        raise ValueError("unreviewed source patch missing")
    patch_content = patch.read_text(encoding="utf-8")
    required = ["diff --git a/evmd/config/bech32.go",
                "diff --git a/evmd/genesis.go",
                "diff --git a/evmd/cmd/evmd/cmd/root.go",
                "diff --git a/evmd/app.go"]
    if any(item not in patch_content for item in required):
        raise ValueError("incomplete application/denomination patch")
    if "GetSupply(ctx, \"aprvi\")" not in patch_content:
        raise ValueError("PRVI supply-cap inspection missing from overlay")
    return {
        "schema_version": 1,
        "classification": "CI_SYNTHETIC_NONPRODUCTION_BINARY_HASH_ONLY",
        "build_commit": commit.lower(),
        "workflow_ref": ref,
        "pinned_upstream_commit": PIN,
        "go_toolchain": go_version,
        "binary_sha256": digest(binary),
        "source_patch_sha256": digest(patch),
        "ci_config_sha256": digest(config),
        "synthetic_cosmos_chain_id": CI_COSMOS,
        "synthetic_evm_chain_id": CI_EVM,
        "native_fee_denom_under_review": "aprvi",
        "proposed_max_supply_base_units": CAP,
        "contains_signing_keys": False,
        "contains_wallet_allocations": False,
        "production_binary_uploaded": False,
        "approved_for_financial_mainnet": False,
        "independent_security_audit_complete": False,
        "notes": [
            "This report records an unreviewed throwaway executable hash only.",
            "The CI executable is intentionally NOT uploaded or deployed.",
            "Release approval requires independent security audits, approved genesis, independent validator attestations and manual launch authorization."
        ]
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", required=True, type=Path)
    p.add_argument("--patch", required=True, type=Path)
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--ref", default=os.environ.get("GITHUB_REF", ""))
    p.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""))
    a = p.parse_args()
    try:
        if a.output.exists() or a.output.is_symlink():
            raise ValueError("refusing to overwrite an existing build receipt")
        go_version = subprocess.check_output(["go", "version"], text=True).strip()
        receipt = make_receipt(a.binary, a.patch, a.config,
                               ref=a.ref, commit=a.commit, go_version=go_version)
        a.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print("BLOCKED: cannot attest synthetic CI build:", exc, file=sys.stderr)
        return 1
    print("NONPRODUCTION hash-only build report created:", a.output)
    print("CI candidate executable is NOT an audited PRVI mainnet or distributable release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
