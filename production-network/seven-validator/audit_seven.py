#!/usr/bin/env python3
"""Audit SEVEN actual CometBFT voting validator addresses across seven RPC nodes.

Designed for one-owner, valueless TEST staging. Seven distinct signer keys
DO NOT establish seven independent operator businesses.
"""
import argparse
import json
import sys
from pathlib import Path

TESTNET_DIR=Path(__file__).resolve().parents[1]/"testnet"
sys.path.insert(0,str(TESTNET_DIR))
from consensus_audit import audit, get, validator_set

COUNT=7
CHAIN="local-privi-seven-4221"
RPC_PORTS=[26657+10*i for i in range(COUNT)]

def check(urls,expected=CHAIN):
    if len(urls)!=COUNT or len(set(urls))!=COUNT:
        raise ValueError("Exactly seven DIFFERENT CometBFT RPC endpoints required")
    info=audit(urls,expected=expected)
    if info.get("nodes")!=COUNT or info.get("votingValidators")!=COUNT:
        raise ValueError("Expected exactly seven distinct live voting validators")
    height=info["blockHeight"]
    powers=validator_set(urls[0],height)
    if len(powers)!=COUNT:
        raise ValueError("Consensus validator set does not contain exactly seven keys")
    total=sum(powers.values())
    if any(v<=0 or 3*v>=total for v in powers.values()):
        raise ValueError("Invalid voting power / one validator >= one-third")
    commit=get(urls[0],f"/commit?height={height}")["signed_header"]["commit"]
    signers={s.get("validator_address","").upper()
             for s in commit["signatures"]
             if str(s.get("block_id_flag")) in ("2","BLOCK_ID_FLAG_COMMIT")
             and s.get("signature")}
    signed_distinct=len(signers & powers.keys())
    if signed_distinct!=COUNT:
        raise ValueError(f"Only {signed_distinct}/7 real validator signatures on selected block")
    return {
        "ok":True,
        "cosmosChainId":expected,
        "evmReferenceChainId":262144,
        "height":height,
        "agreedBlockHash":info["blockHash"],
        "votingValidatorKeys":len(powers),
        "distinctSigners":signed_distinct,
        "votingPowerSigned":info["signedVotingPower"],
        "votingPowerTotal":info["totalVotingPower"],
        "ownerIndependence":"ONE operator controls all seven; NOT decentralized production mainnet"
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rpc",action="append",default=[])
    p.add_argument("--chain-id",default=CHAIN)
    args=p.parse_args()
    urls=args.rpc or [f"http://127.0.0.1:{port}" for port in RPC_PORTS]
    try:
        print(json.dumps(check(urls,args.chain_id),indent=2))
    except Exception as exc:
        print(json.dumps({"ok":False,"error":str(exc)}))
        raise SystemExit(1) from exc

if __name__=="__main__":main()
