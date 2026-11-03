#!/usr/bin/env python3
"""Offline collision check for PROPOSED Privi chain IDs; not registry approval.

Use fresh, independently sourced JSON snapshots. No network calls, deployments,
keys or genesis generation. A local no-conflict result is NOT proof of reservation.
"""
import argparse
import json
import re
from pathlib import Path

KNOWN_DEMO={1,56,97,4221,262144,31337,1337}
CAP="1000000000000000000000000000"

def check(candidate, evm_registry, cosmos_registry):
    problems=[]
    if candidate.get("status")!="PROPOSED_UNRESERVED_NOT_FOR_GENESIS":
        problems.append("candidate status must remain explicitly unreserved")
    cid=candidate.get("cosmos_chain_id")
    eid=candidate.get("evm_chain_id")
    if not isinstance(cid,str) or re.fullmatch(r"[a-z][a-z0-9-]{2,63}",cid) is None or cid.startswith(("local-","test-","privi-dev")):
        problems.append("fresh production-shaped Cosmos ID required")
    if type(eid) is not int or eid<1000 or eid>4294967295 or eid in KNOWN_DEMO:
        problems.append("fresh, non-demo EIP-155 chain ID required")
    coin=candidate.get("coin") or {}
    if {k:coin.get(k) for k in ("symbol","base_denom","decimals","max_supply_base_units")} != {
        "symbol":"PRVI","base_denom":"aprvi","decimals":18,"max_supply_base_units":CAP}:
        problems.append("PRVI denom/decimals/supply cap mismatch")
    if not isinstance(evm_registry,list) or not isinstance(cosmos_registry,list):
        problems.append("two complete JSON array registry snapshots are required")
        return problems
    if len(evm_registry)==0 or len(cosmos_registry)==0:
        problems.append("registry snapshots cannot be empty")
    evm_ids=[item.get("chainId") for item in evm_registry if isinstance(item,dict)]
    cosmos_ids=[item.get("chain_id") for item in cosmos_registry if isinstance(item,dict)]
    if eid in evm_ids:problems.append("EVM chain ID collision in supplied snapshot")
    if cid in cosmos_ids:problems.append("Cosmos chain ID collision in supplied snapshot")
    if any(type(v) is not int for v in evm_ids):
        problems.append("invalid EVM registry snapshot entry")
    if any(not isinstance(v,str) or not v for v in cosmos_ids):
        problems.append("invalid Cosmos registry snapshot entry")
    return problems

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate",type=Path,default=Path(__file__).with_name("candidate_network_ids.json"))
    p.add_argument("--evm-registry",required=True,type=Path,help="Fresh complete https://chainid.network/chains.json snapshot")
    p.add_argument("--cosmos-registry",required=True,type=Path,help="Fresh aggregated Cosmos chain registry IDs array")
    a=p.parse_args()
    errs=check(json.loads(a.candidate.read_text()),json.loads(a.evm_registry.read_text()),json.loads(a.cosmos_registry.read_text()))
    if errs:
        print("CANDIDATE NOT CLEARED: "+"; ".join(errs))
        return 1
    print("NO COLLISIONS IN SUPPLIED SNAPSHOTS ONLY. Registry submission/approval and human verification REQUIRED.")
    return 0

if __name__=="__main__":raise SystemExit(main())
