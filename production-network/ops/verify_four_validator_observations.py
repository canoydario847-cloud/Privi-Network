#!/usr/bin/env python3
"""Offline four-validator Privi staging RPC concordance check.

Consumes FOUR captured /status and eth_chainId response pairs from a reviewed
local directory. No outbound requests, keys, token creation, signing, remote
host management or financial mainnet activation. These snapshots are NOT
authenticated by this tool and do not establish an independent public testnet.

Require a shared observed height and hash (no inference of same-chain
consensus from different-height snapshots), four unique Comet node IDs and
four distinct, nonzero-power validator addresses.
"""
import argparse
import json
import re
from pathlib import Path

from strict_json_evidence import load as load_strict_json
from verify_node_identity import verify as verify_node_identity

IDS = {f"privi-owner-val-{i:02d}" for i in range(1, 5)}
HEX40 = re.compile(r"^[0-9A-Fa-f]{40}$")
DECIMAL = re.compile(r"^[1-9][0-9]*$")
SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9_-][a-zA-Z0-9_.-]{0,99}\.json$")
MAX_SNAPSHOT_BYTES = 1_048_576


def _obj(value, name):
    if not isinstance(value, dict):
        raise ValueError(name + " must be an object")
    return value


def _snapshot(base: Path, filename):
    if not isinstance(filename, str) or not SAFE_FILENAME.fullmatch(filename):
        raise ValueError("snapshot filename must be one local, safe .json basename")
    parent = base.resolve(strict=True)
    file = base / filename
    if file.is_symlink() or not file.is_file():
        raise ValueError("snapshot missing or symlinked")
    if file.resolve(strict=True).parent != parent:
        raise ValueError("snapshot escapes the trusted input directory")
    if file.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError("snapshot exceeds 1 MiB review limit")
    return load_strict_json(file)


def verify(bundle, base: Path):
    bundle = _obj(bundle, "bundle")
    if set(bundle) != {"schema_version", "purpose", "cosmos_chain_id",
                       "evm_chain_id", "nodes"}:
        raise ValueError("bundle has missing or extra review fields")
    if type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1:
        raise ValueError("bundle schema version must be 1")
    if bundle["purpose"] != "valueless-four-host-staging":
        raise ValueError("only valueless four-host staging is supported")
    cosmos_id, evm_id = bundle["cosmos_chain_id"], bundle["evm_chain_id"]
    nodes = bundle["nodes"]
    if not isinstance(nodes, list) or len(nodes) != 4:
        raise ValueError("exactly four local node observations required")

    seen_ids, peer_ids, validator_addresses, filenames = set(), set(), set(), set()
    observations = []
    for index, entry in enumerate(nodes):
        entry = _obj(entry, "node observation")
        if set(entry) != {"id", "comet_status", "eth_chain_id"}:
            raise ValueError("node has missing or extra review fields")
        name = entry["id"]
        if not isinstance(name, str) or name not in IDS or name in seen_ids:
            raise ValueError("four unique, exact Privi staging node IDs required")
        seen_ids.add(name)
        for key in ("comet_status", "eth_chain_id"):
            filename = entry[key]
            if not isinstance(filename, str) or filename in filenames:
                raise ValueError("each observation must use a distinct local JSON file")
            filenames.add(filename)

        comet = _snapshot(base, entry["comet_status"])
        eth = _snapshot(base, entry["eth_chain_id"])
        identity = verify_node_identity(comet, eth, cosmos_id, evm_id)
        result = _obj(_obj(comet, "Comet status").get("result"), "Comet result")
        node = _obj(result.get("node_info"), "Comet node_info")
        sync = _obj(result.get("sync_info"), "Comet sync_info")
        validator = _obj(result.get("validator_info"), "Comet validator_info")
        peer = node.get("id")
        address = validator.get("address")
        power = validator.get("voting_power")
        if not isinstance(peer, str) or not HEX40.fullmatch(peer):
            raise ValueError("Comet node ID must be 40 hex characters")
        if not isinstance(address, str) or not HEX40.fullmatch(address):
            raise ValueError("Comet validator consensus address must be 40 hex characters")
        if not isinstance(power, str) or not DECIMAL.fullmatch(power):
            raise ValueError("Comet validator must declare positive integer voting power")
        if peer.lower() in peer_ids or address.lower() in validator_addresses:
            raise ValueError("duplicate peer ID or validator signing address")
        peer_ids.add(peer.lower())
        validator_addresses.add(address.lower())
        observations.append({
            "validator_id": name,
            "height": identity["observed_height"],
            "hash": sync["latest_block_hash"].lower(),
        })

    if seen_ids != IDS:
        raise ValueError("four exact Privi staging IDs 01-04 required")
    if len({row["height"] for row in observations}) != 1:
        raise ValueError("four nodes observed at different heights; recapture same-height snapshots")
    if len({row["hash"] for row in observations}) != 1:
        raise ValueError("four nodes disagree on block hash at the same height")
    return {
        "observation": "FOUR_UNAUTHENTICATED_SNAPSHOTS_CONCUR",
        "cosmos_chain_id": cosmos_id,
        "evm_chain_id": evm_id,
        "observed_height": observations[0]["height"],
        "distinct_comet_peers": len(peer_ids),
        "distinct_validator_addresses": len(validator_addresses),
        "operator_architecture": "ONE_OWNER_FOUR_HOSTS_NOT_FOUR_INDEPENDENT_OPERATORS",
        "financial_mainnet": "NO_GO_REQUIRES_EXTERNAL_EVIDENCE",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path,
                        help="local nonsecret manifest referencing four snapshots")
    args = parser.parse_args()
    try:
        if args.bundle.is_symlink():
            raise ValueError("symlinked bundle files are not accepted")
        if args.bundle.stat().st_size > MAX_SNAPSHOT_BYTES:
            raise ValueError("bundle exceeds 1 MiB review limit")
        result = verify(load_strict_json(args.bundle), args.bundle.parent)
    except (ValueError, OSError, UnicodeError) as exc:
        # Do not print arbitrary filenames, snapshots, secret data or RPC payloads.
        print("FOUR-NODE OBSERVATION FAILED:", type(exc).__name__, str(exc))
        return 2
    print(json.dumps(result, sort_keys=True))
    print("NO EXTERNAL ATTESTATION, CONSENSUS SIGNATURE OR FINANCIAL LAUNCH AUTHORIZATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
