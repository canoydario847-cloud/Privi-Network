#!/usr/bin/env python3
"""Read-only proof-of-observation of a Privi candidate node's two chain IDs.

Consumes locally captured CometBFT /status and eth_chainId JSON-RPC replies.
Makes NO HTTP/SSH requests, creates no validator keys or tokens, never signs
and NEVER authorizes a financial mainnet. A captured reply is not authenticated
by this script; separately attest endpoint provenance and release/genesis hash.
"""
import argparse
import json
import re
from pathlib import Path
from strict_json_evidence import load as load_strict_json

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_HEIGHT = re.compile(r"^[1-9][0-9]*$")
_ETH_ID = re.compile(r"^0x[0-9a-fA-F]+$")

def obj(value, context):
    if not isinstance(value, dict):
        raise ValueError(context + " must be a JSON object")
    return value

def verify(comet, eth, expected_cosmos_id, expected_evm_id):
    if (not isinstance(expected_cosmos_id, str) or
            not re.fullmatch(r"[A-Za-z0-9_-]{5,80}",expected_cosmos_id)):
        raise ValueError("expected Cosmos ID must be a reviewed nonempty identifier")
    if type(expected_evm_id) is not int or not (0 < expected_evm_id <= 2**64-1):
        raise ValueError("expected EVM ID must be a positive uint64")
    cr = obj(obj(comet, "Comet status").get("result"), "Comet result")
    node = obj(cr.get("node_info"), "Comet node_info")
    sync = obj(cr.get("sync_info"), "Comet sync_info")
    if node.get("network") != expected_cosmos_id:
        raise ValueError("Comet node chain ID differs from expected Cosmos chain")
    if sync.get("catching_up") is not False:
        raise ValueError("Comet node is catching up or sync state is not verified")
    height = sync.get("latest_block_height")
    if not isinstance(height, str) or not _HEIGHT.fullmatch(height):
        raise ValueError("Comet block height must be canonical positive decimal text")
    if int(height) < 2:
        raise ValueError("node must have finalized at least two blocks")
    block_hash = sync.get("latest_block_hash")
    if not isinstance(block_hash, str) or not _HEX64.fullmatch(block_hash):
        raise ValueError("latest finalized block hash must have 64 hex digits")
    er = obj(eth, "Ethereum RPC reply")
    if "error" in er:
        raise ValueError("eth_chainId replied with an error")
    actual = er.get("result")
    if not isinstance(actual, str) or not _ETH_ID.fullmatch(actual):
        raise ValueError("eth_chainId must be a canonical hex JSON-RPC result")
    if int(actual, 16) != expected_evm_id:
        raise ValueError("EVM chain ID differs from expected candidate chain")
    # This cannot prove the captured responses came from a particular VPS
    # or that the observed node ran the signed release or genesis bytes.
    return {
        "observation": "MATCHES_DECLARED_NODE_IDENTITIES_ONLY",
        "cosmos_chain_id":expected_cosmos_id,
        "evm_chain_id":expected_evm_id,
        "observed_height":int(height),
        "financial_mainnet": "NO_GO_REQUIRES_EXTERNAL_EVIDENCE",
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--comet-status",type=Path,required=True)
    p.add_argument("--eth-chain-id",type=Path,required=True)
    p.add_argument("--expected-cosmos-id",required=True)
    p.add_argument("--expected-evm-id",required=True,type=int)
    args=p.parse_args()
    try:
        report=verify(load_strict_json(args.comet_status),
                      load_strict_json(args.eth_chain_id),
                      args.expected_cosmos_id,args.expected_evm_id)
    except (OSError,ValueError,UnicodeError) as exc:
        print("IDENTITY CHECK FAILED:",str(exc))
        return 2
    print(json.dumps(report,sort_keys=True))
    print("READ-ONLY OBSERVATION; NOT AN INDEPENDENT ATTESTATION OR FINANCIAL MAINNET AUTHORIZATION")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
