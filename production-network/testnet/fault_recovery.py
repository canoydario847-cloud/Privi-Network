#!/usr/bin/env python3
"""CI-only stop/restart of ONE disposable EVM developer validator container.

Observe block production at >2/3 power while down, then restart and verify
the recovered validator signs a later finalized block. No validator secrets
are exported; DO NOT use on public or real-money infrastructure.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError

from consensus_audit import get, validator_set
from evm_smoke import RPC

URLS = ("http://127.0.0.1:26657", "http://127.0.0.1:26667",
        "http://127.0.0.1:26677", "http://127.0.0.1:26687")
EXPECTED = "local-4221"
EVM_ID = 262144
HEX40 = re.compile(r"^[A-Fa-f0-9]{40}$")
HEX64 = re.compile(r"^[A-Fa-f0-9]{64}$")


def safe_gate(root, env):
    if env.get("CI") != "true" or env.get("PRIVI_EPHEMERAL_TRANSFER_TEST") != "1":
        raise ValueError("CI-only and explicitly opted-in disposable network required")
    if not isinstance(root, Path) or root.name != ".upstream-evm":
        raise ValueError("refusing non-upstream dev checkout")
    if not (root / "docker-compose.localhost.yml").is_file():
        raise ValueError("missing disposable localhost-only Compose file")


def inspect_commit(urls, height, missing=None, required=None):
    if not isinstance(height, int) or height < 1:
        raise ValueError("invalid comparison height")
    statuses = [get(u, "/status") for u in urls]
    ids = [s["node_info"]["id"] for s in statuses]
    if len(set(ids)) != len(urls):
        raise ValueError("duplicate node IDs")
    chains = [s["node_info"]["network"] for s in statuses]
    if any(x != EXPECTED for x in chains):
        raise ValueError("wrong Cosmos chain ID")
    heights = [int(s["sync_info"]["latest_block_height"]) for s in statuses]
    if min(heights) <= height or max(heights) - min(heights) > 10:
        raise ValueError("nodes failed to progress and synchronize")
    if any(s["sync_info"]["catching_up"] for s in statuses):
        raise ValueError("validator is still syncing")
    target = min(heights) - 1
    hashes = [get(u, "/block?height=" + str(target))["block_id"]["hash"].upper()
              for u in urls]
    if len(set(hashes)) != 1 or not HEX64.fullmatch(hashes[0]):
        raise ValueError("observer block hash mismatch")
    sets = [validator_set(u, target) for u in urls]
    if any(x != sets[0] for x in sets[1:]):
        raise ValueError("validator voting sets disagree")
    live = {a: p for a, p in sets[0].items() if p > 0}
    if len(live) != 4:
        raise ValueError("expected exactly 4 local dev validators")
    signed_header = get(urls[0], "/commit?height=" + str(target))["signed_header"]
    commit = signed_header["commit"]
    if str(commit["block_id"]["hash"]).upper() != hashes[0]:
        raise ValueError("commit block hash mismatch")
    signed = {
        x.get("validator_address", "").upper()
        for x in commit["signatures"]
        if str(x.get("block_id_flag")) in ("2", "BLOCK_ID_FLAG_COMMIT") and x.get("signature")
    }
    total = sum(live.values())
    signed_power = sum(power for addr, power in live.items() if addr in signed)
    if total <= 0 or signed_power * 3 <= total * 2:
        raise ValueError("no >2/3 voting-power commit")
    if missing is not None:
        if missing not in live:
            raise ValueError("stopped validator not a live member")
        if missing in signed:
            raise ValueError("stopped validator still signed during controlled outage")
    if required is not None and required not in signed:
        raise ValueError("restarted validator not yet included in commit signatures")
    return {"block_height": target, "block_hash": hashes[0],
            "signed_voting_power": signed_power, "total_voting_power": total,
            "signed_validators": len(signed), "observer_count": len(urls)}


def compose(root, action):
    if action not in ("start", "stop"):
        raise ValueError("unsupported Docker action")
    subprocess.run(["docker", "compose", "-f", "docker-compose.localhost.yml",
                    action, "evmdnode3"], cwd=root, check=True, timeout=75,
                   stdin=subprocess.DEVNULL)


def retry_check(urls, minimum, timeout_seconds, **kwargs):
    deadline = time.monotonic() + timeout_seconds
    last = None
    while time.monotonic() < deadline:
        try:
            return inspect_commit(urls, minimum, **kwargs)
        except (ValueError, URLError, KeyError, RuntimeError, TimeoutError,
                ConnectionError, OSError) as exc:
            last = str(exc)
            time.sleep(4)
    raise RuntimeError("consensus evidence not observed before timeout: " + str(last)[:180])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve(strict=True)
    safe_gate(root, os.environ)
    rpc = RPC("http://127.0.0.1:8545")
    if int(rpc.call("eth_chainId"), 16) != EVM_ID:
        raise ValueError("wrong EVM identity; refusing Docker stop/restart")
    statuses = [get(u, "/status") for u in URLS]
    for status in statuses:
        if status["node_info"]["network"] != EXPECTED:
            raise ValueError("wrong Cosmos ID; refusing Docker stop/restart")
    stopped_address = statuses[3]["validator_info"]["address"].upper()
    if not HEX40.fullmatch(stopped_address):
        raise ValueError("unrecognized stopped consensus address")
    height_before = min(int(x["sync_info"]["latest_block_height"]) for x in statuses)
    if height_before < 2:
        raise ValueError("need stable four-node baseline")
    stopped = False
    try:
        compose(root, "stop")
        stopped = True
        outage = retry_check(URLS[:3], height_before + 1, 140, missing=stopped_address)
        compose(root, "start")
        stopped = False
        recovery = retry_check(URLS, outage["block_height"] + 1, 180,
                               required=stopped_address)
        if int(rpc.call("eth_chainId"), 16) != EVM_ID:
            raise ValueError("wrong EVM identity after recovery")
        print(json.dumps({
            "status": "DISPOSABLE_LOCAL_VALIDATOR_OUTAGE_AND_RECOVERY_VERIFIED",
            "cosmos_chain_id": EXPECTED, "evm_chain_id": EVM_ID,
            "stopped_consensus_address": stopped_address,
            "before_height": height_before, "during_outage": outage,
            "after_restart": recovery, "recovered_validator_signed": True,
            "warning": "One disposable same-runner validator restart does NOT establish independent host/fault-domain recovery or public mainnet readiness"
        }, indent=2))
        return 0
    finally:
        if stopped:
            # Never leave devnet stopped if a probe fails partway through.
            try:
                compose(root, "start")
            except Exception as exc:
                print("Warning: disposable node restart failed: " + str(exc)[:150], file=sys.stderr)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, RuntimeError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:200]}), file=sys.stderr)
        sys.exit(1)
