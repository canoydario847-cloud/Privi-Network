#!/usr/bin/env python3
"""Read-only verification of a separately signed *valueless devnet* EVM transfer.

This NEVER signs or broadcasts a transaction, creates funds, or establishes
production readiness. Supply an already mined transaction hash.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from evm_smoke import RPC

TXHASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")

def hexint(raw, label):
    if not isinstance(raw,str) or not re.fullmatch(r"0x[0-9a-fA-F]+",raw):
        raise ValueError(label+" must be hexadecimal JSON-RPC quantity")
    return int(raw,16)

def check(rpc, tx_hash, chain_id, sender, recipient, amount_wei, confirmations=1):
    if not TXHASH.fullmatch(tx_hash):
        raise ValueError("invalid transaction hash")
    if not isinstance(chain_id,int) or isinstance(chain_id,bool) or chain_id<=0:
        raise ValueError("invalid expected EVM chain ID")
    for label,addr in (("sender",sender),("recipient",recipient)):
        if not isinstance(addr,str) or not ADDRESS.fullmatch(addr):
            raise ValueError("invalid "+label+" address")
    if not isinstance(amount_wei,int) or isinstance(amount_wei,bool) or amount_wei<=0:
        raise ValueError("amount_wei must be a positive integer")
    if not isinstance(confirmations,int) or isinstance(confirmations,bool) or confirmations<1:
        raise ValueError("confirmations must be >= 1")
    actual_chain=hexint(rpc.call("eth_chainId"),"eth_chainId")
    if actual_chain!=chain_id:
        raise ValueError("EVM chain ID mismatch: expected %d, observed %d"%(chain_id,actual_chain))
    tx=rpc.call("eth_getTransactionByHash",[tx_hash])
    receipt=rpc.call("eth_getTransactionReceipt",[tx_hash])
    if not isinstance(tx,dict) or not isinstance(receipt,dict):
        raise ValueError("transaction or receipt missing (pending, not indexed, or unknown)")
    if str(tx.get("hash","")).lower()!=tx_hash.lower() or str(receipt.get("transactionHash","")).lower()!=tx_hash.lower():
        raise ValueError("transaction hash mismatch")
    for key,expected in (("from",sender),("to",recipient)):
        if str(tx.get(key,"")).lower()!=expected.lower():
            raise ValueError("unexpected transaction "+key)
    if hexint(tx.get("value"),"tx value")!=amount_wei:
        raise ValueError("transferred native amount differs from expected")
    if tx.get("input") not in ("0x","0x0",""):
        raise ValueError("not an ordinary native-coin transfer (nonempty calldata)")
    if "chainId" in tx and tx["chainId"] is not None and hexint(tx["chainId"],"tx chain ID")!=chain_id:
        raise ValueError("signed transaction chain ID differs from RPC chain ID")
    if hexint(receipt.get("status"),"receipt status")!=1:
        raise ValueError("transaction failed or receipt status not successful")
    height=hexint(receipt.get("blockNumber"),"receipt blockNumber")
    latest=hexint(rpc.call("eth_blockNumber"),"latest block")
    if height<1 or height>latest or (latest-height+1)<confirmations:
        raise ValueError("insufficient confirmations")
    block=rpc.call("eth_getBlockByNumber",[hex(height),False])
    if not isinstance(block,dict):
        raise ValueError("receipt block missing")
    blockhash=block.get("hash")
    if not isinstance(blockhash,str) or not TXHASH.fullmatch(blockhash):
        raise ValueError("invalid block hash")
    if str(tx.get("blockHash","")).lower()!=blockhash.lower() or str(receipt.get("blockHash","")).lower()!=blockhash.lower():
        raise ValueError("block hash disagreement")
    if tx_hash.lower() not in [str(h).lower() for h in block.get("transactions",[])]:
        raise ValueError("transaction not included in claimed block")
    return {"ok":True,"evm_chain_id":actual_chain,"tx_hash":tx_hash,
            "sender":sender,"recipient":recipient,"value_wei":str(amount_wei),
            "block_height":height,"block_hash":blockhash,"confirmations":latest-height+1,
            "warning":"Only a disposable, valueless developer transaction is verified; does not certify production or prove balance changes"}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rpc",default="http://127.0.0.1:8545")
    ap.add_argument("--tx-hash",required=True)
    ap.add_argument("--expect-chain",required=True,type=int)
    ap.add_argument("--sender",required=True)
    ap.add_argument("--recipient",required=True)
    ap.add_argument("--value-wei",required=True,type=int)
    ap.add_argument("--min-confirmations",type=int,default=1)
    a=ap.parse_args()
    try:
        result=check(RPC(a.rpc),a.tx_hash,a.expect_chain,a.sender,a.recipient,a.value_wei,a.min_confirmations)
    except (ValueError,KeyError,TypeError,RuntimeError,OSError) as e:
        print(json.dumps({"ok":False,"error":str(e)}))
        return 1
    print(json.dumps(result,indent=2))
    return 0

if __name__=="__main__":sys.exit(main())
