#!/usr/bin/env python3
"""Fail-closed, build-only validation of Privi's pinned Cosmos SDK overlay.

Consumes Go module-graph JSON and go version -m output from the same
isolated custom-node build. This is build-input evidence, NOT a signature,
audit, launch approval, or proof of production execution.
"""
import argparse
import hashlib
import json
from pathlib import Path

SDK = "github.com/cosmos/cosmos-sdk"
VERSION = "v0.54.3"
MARKERS = {
    "x/bank/keeper/send.go": (
        "func (k BaseSendKeeper) setBalanceForBankOperation(",
        "PRVI SDK bank: external native balance write forbidden",
    ),
    "x/bank/keeper/keeper.go": (
        'amounts.AmountOf("aprvi").IsPositive()',
        "PRVI SDK bank: native aprvi mint forbidden",
    ),
    "x/bank/keeper/genesis.go": (
        "var priviBankGenesisApplied = []byte{",
        "PRVI SDK bank: repeated InitGenesis forbidden",
        "rawKV.Set(priviBankGenesisApplied, []byte{1})",
    ),
}


def verify(module_json: str, build_info: str, sdk_dir: Path) -> dict:
    root = sdk_dir.resolve(strict=True)
    if not root.is_dir() or root.name != "privi-patched-sdk-app-only":
        raise ValueError("untrusted or nonexistent disposable SDK build directory")
    module = json.loads(module_json)
    replacement = module.get("Replace") or {}
    if module.get("Path") != SDK or module.get("Version") != VERSION:
        raise ValueError("incorrect Cosmos SDK module/version in Go dependency graph")
    if replacement.get("Path") != str(root) or replacement.get("Dir") != str(root):
        raise ValueError("Go module graph did not use exact disposable hardened SDK")
    lines = [line.strip().split("\t") for line in build_info.splitlines()]
    valid_binary_dependency = False
    for i, fields in enumerate(lines):
        if len(fields) >= 3 and fields[:3] == ["dep", SDK, VERSION]:
            if i + 1 < len(lines):
                next_fields = lines[i + 1]
                valid_binary_dependency = (len(next_fields) >= 2 and
                                           next_fields[0] == "=>" and
                                           next_fields[1] == str(root))
            break
    if not valid_binary_dependency:
        raise ValueError("compiled binary does not identify the pinned patched SDK replacement")
    fingerprints = {}
    for relpath, required in MARKERS.items():
        path = root / relpath
        data = path.read_bytes()
        content = data.decode("utf-8")
        for marker in required:
            if content.count(marker) != 1:
                raise ValueError("hardened SDK source missing unique guard in " + relpath)
        fingerprints[relpath] = hashlib.sha256(data).hexdigest()
    return {
        "status": "BUILD_ONLY_SDK_INPUT_VERIFIED",
        "financial_mainnet": "NO_GO",
        "pinned_module": SDK + "@" + VERSION,
        "security_source_sha256": fingerprints,
        "warning": "Go build provenance only: not a signed artifact or runtime consensus audit",
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--module-json", type=Path, required=True)
    cli.add_argument("--build-info", type=Path, required=True)
    cli.add_argument("--sdk-dir", type=Path, required=True)
    args = cli.parse_args()
    result = verify(args.module_json.read_text(encoding="utf-8"),
                    args.build_info.read_text(encoding="utf-8"), args.sdk_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
