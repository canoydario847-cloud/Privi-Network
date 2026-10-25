#!/usr/bin/env python3
"""Read-only PRVI EVM/CometBFT quorum observation. Never a financial launch authorization.

Requires independently approved IDs and real reachable RPC endpoints.
Does NOT support local-4221/262144 developer TEST chain. No signing, fees or state changes.
"""
import argparse
import json
import sys
import time
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen

BLOCK_TIME_LIMIT=180
DEMO_IDS={262144,4221,56,97,1}

def get(url):
    with urlopen(Request(url,headers={"User-Agent":"Privi-Mainnet-ReadOnly-Health/1"}),
                 timeout=12) as res:
        if res.status!=200: raise RuntimeError(f"HTTP {res.status}")
        return json.load(res)

def post(url,method,params=None):
    body=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params or []}).encode()
    with urlopen(Request(url,body,headers={"Content-Type":"application/json",
                                          "User-Agent":"Privi-Mainnet-ReadOnly-Health/1"},
                              method="POST"),timeout=12) as res:
        if res.status!=200: raise RuntimeError(f"{method} HTTP {res.status}")
        data=json.load(res)
        if data.get("error"):raise RuntimeError(f"{method} RPC error: {data['error']}")
        return data["result"]

def check(evm_rpc,comet_rpc,expected_cosmos,expected_evm,now=None):
    if (not isinstance(expected_cosmos,str)
            or not expected_cosmos.startswith("privi-")
            or expected_cosmos in ("local-4221","privi-dev-1")):
        raise RuntimeError("This monitor is mainnet-only; choose independently reviewed Privi chain ID")
    if type(expected_evm) is not int or expected_evm<=1000 or expected_evm in DEMO_IDS:
        raise RuntimeError("Demo/test/BNB chain ID forbidden")
    for url in (evm_rpc,comet_rpc):
        x=urlsplit(url)
        if x.scheme not in ("http","https") or not x.hostname or x.username or x.password:
            raise RuntimeError("Malformed RPC URL or URL contains credentials")
        if x.scheme=="http" and x.hostname not in ("127.0.0.1","localhost","::1"):
            raise RuntimeError("Remote monitoring RPC URL must use HTTPS")

    chain=int(post(evm_rpc,"eth_chainId"),16)
    if chain!=expected_evm:raise RuntimeError(f"Wrong EVM chain: {chain} != {expected_evm}")
    evmheight=int(post(evm_rpc,"eth_blockNumber"),16)
    if evmheight<2: raise RuntimeError("EVM chain has not finalized enough blocks")
    evmblock=post(evm_rpc,"eth_getBlockByNumber",[hex(evmheight),False])
    if not evmblock or not evmblock.get("hash"):raise RuntimeError("Missing latest block hash")
    timestamp=int(evmblock["timestamp"],16)
    now=int(time.time()) if now is None else int(now)
    if timestamp>now+30 or now-timestamp>BLOCK_TIME_LIMIT:
        raise RuntimeError("EVM latest block is stale or from the future")

    status=get(comet_rpc.rstrip("/")+"/status")["result"]
    if status["node_info"]["network"]!=expected_cosmos:
        raise RuntimeError("CometBFT Cosmos chain ID mismatch")
    sync=status["sync_info"]
    if sync.get("catching_up") not in (False,"false"):
        raise RuntimeError("Consensus RPC reports node catching up")
    height=int(sync["latest_block_height"])
    if abs(height-evmheight)>3:
        raise RuntimeError(f"Comet and EVM RPC heights diverge: {height} vs {evmheight}")

    # Comet RPC /validators returns the actual current power set, NOT peers.
    query=urlencode({"height":str(height),"per_page":"100"})
    vals=get(comet_rpc.rstrip("/")+"/validators?"+query)["result"]
    validators=vals.get("validators",[])
    count=int(vals.get("total",len(validators)))
    if count<4 or count>100 or len(validators)!=count:
        raise RuntimeError("Need at least four actual voting validators and a complete unpaginated validator set")
    power={}
    for validator in validators:
        addr=str(validator["address"]).upper()
        if len(addr)!=40 or any(c not in "0123456789ABCDEF" for c in addr):
            raise RuntimeError("CometBFT validator address must be 20-byte hex")
        if addr in power:
            raise RuntimeError("Duplicate CometBFT consensus validator address")
        power[addr]=int(validator["voting_power"])
    if len(power)!=count or any(x<=0 for x in power.values()):
        raise RuntimeError("Bad validator address or voting power")
    total=sum(power.values())
    if any(3*x>=total for x in power.values()):
        raise RuntimeError("At least one validator has >= 1/3 of voting power")
    commit=get(comet_rpc.rstrip("/")+"/commit?"+urlencode({"height":str(height)}))["result"]
    header=commit["signed_header"]["header"]
    if str(header.get("height"))!=str(height):
        raise RuntimeError("CometBFT commit header height mismatch")
    if header.get("chain_id")!=expected_cosmos:
        raise RuntimeError("CometBFT commit header chain ID mismatch")
    # A vote count is not proof of the block being reported. The commit,
    # its signed header, and the independently queried block at this height
    # must agree. CometBFT block hashes are NOT Ethereum block hashes.
    commit_record=commit["signed_header"]["commit"]
    if str(commit_record.get("height"))!=str(height):
        raise RuntimeError("CometBFT commit vote height mismatch")
    commit_block_id=commit_record.get("block_id")
    commit_hash=commit_block_id.get("hash") if isinstance(commit_block_id,dict) else None
    if (not isinstance(commit_hash,str) or len(commit_hash)!=64
            or any(c not in "0123456789abcdefABCDEF" for c in commit_hash)):
        raise RuntimeError("CometBFT commit block hash invalid")
    block=get(comet_rpc.rstrip("/")+"/block?"+urlencode({"height":str(height)}))["result"]
    block_id=block.get("block_id")
    block_hash=block_id.get("hash") if isinstance(block_id,dict) else None
    if not isinstance(block_hash,str) or block_hash.upper()!=commit_hash.upper():
        raise RuntimeError("CometBFT block hash differs from signed commit")
    block_record=block.get("block")
    block_header=block_record.get("header") if isinstance(block_record,dict) else None
    if (not isinstance(block_header,dict)
            or str(block_header.get("height"))!=str(height)
            or block_header.get("chain_id")!=expected_cosmos):
        raise RuntimeError("CometBFT fetched block header mismatch")
    signed=commit_record["signatures"]
    signers=set()
    for signature in signed:
        # Flag 2 is a real commit vote; absent/nil flags do not count.
        if str(signature.get("block_id_flag"))=="2":
            key=str(signature.get("validator_address","")).upper()
            if key in power and key not in signers:signers.add(key)
    signed_power=sum(power.get(k,0) for k in signers)
    if 3*signed_power<=2*total:
        raise RuntimeError("CometBFT latest commit did not have >2/3 voting power")
    return {
      "status":"RPC_QUORUM_OBSERVED_ONLY","financial_mainnet_authorized":False,
      "independent_operator_custody_verified":False,
      "network":expected_cosmos,"evmChainId":expected_evm,
      "latestHeight":height,"evmBlockHash":evmblock["hash"],
      "validatorCount":count,"commitSignedVotingPower":signed_power,
      "totalVotingPower":total,"latestBlockAgeSeconds":now-timestamp,
      "note":"Online quorum alone does NOT prove validator independence, PoP finality, issuance safety or mainnet launch readiness"
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evm-rpc",required=True)
    p.add_argument("--comet-rpc",required=True)
    p.add_argument("--cosmos-chain-id",required=True)
    p.add_argument("--evm-chain-id",required=True,type=int)
    args=p.parse_args()
    try:
        result=check(args.evm_rpc,args.comet_rpc,args.cosmos_chain_id,args.evm_chain_id)
    except (RuntimeError,KeyError,TypeError,ValueError,OSError,TimeoutError) as e:
        print("PRIVI MAINNET HEALTH FAIL:",str(e),file=sys.stderr)
        return 1
    print(json.dumps(result,indent=2))
    return 0
if __name__=="__main__":raise SystemExit(main())
