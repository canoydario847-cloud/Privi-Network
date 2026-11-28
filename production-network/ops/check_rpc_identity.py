#!/usr/bin/env python3
"""Read-only RPC preflight. Passing is not authorization to launch."""
import argparse
import json
import time
import urllib.request
from urllib.parse import urlsplit

def request(url, payload=None):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTPS RPC endpoint without embedded credentials")
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read(2_000_000))

def evm(url, method):
    obj = request(url, {"jsonrpc":"2.0","id":1,"method":method,"params":[]})
    if "error" in obj or obj.get("id") != 1:
        raise ValueError("JSON-RPC error")
    return obj["result"]

def sample(args):
    status = request(args.comet.rstrip("/") + "/status")["result"]
    if status["node_info"]["network"] != args.cosmos_id:
        raise ValueError("Unexpected Cosmos chain ID")
    sync = status["sync_info"]
    if sync["catching_up"] is not False or evm(args.evm, "eth_syncing") is not False:
        raise ValueError("Node is synchronizing")
    if int(evm(args.evm, "eth_chainId"),16) != args.evm_id:
        raise ValueError("Unexpected EVM chain ID")
    comet_height = int(sync["latest_block_height"])
    evm_height = int(evm(args.evm, "eth_blockNumber"),16)
    if min(comet_height, evm_height) <= 0 or abs(comet_height-evm_height)>3:
        raise ValueError("RPC heights inconsistent")
    return comet_height, evm_height

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--comet", required=True)
    p.add_argument("--evm", required=True)
    p.add_argument("--cosmos-id", required=True)
    p.add_argument("--evm-id", required=True, type=int)
    p.add_argument("--interval", type=int, default=30, choices=range(5,121), metavar="5-120")
    args = p.parse_args()
    try:
        before = sample(args)
        time.sleep(args.interval)
        after = sample(args)
        if any(b <= a for a,b in zip(before,after)):
            raise ValueError("Both RPC heights must advance")
        print(json.dumps({"rpc_preflight":"PASS","before":before,"after":after,
                          "mainnet_authorized":False}))
        return 0
    except Exception as exc:
        print(json.dumps({"rpc_preflight":"FAIL","error":str(exc),"mainnet_authorized":False}))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
