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
    genesis=rpc.call("eth_getBlockByNumber",["0x0",False])
    genesis_hash=genesis.get("hash") if isinstance(genesis,dict) else None
    if not isinstance(genesis_hash,str) or not TXHASH.fullmatch(genesis_hash):
        raise ValueError("missing valid developer genesis block hash")
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
    if hexint(tx.get("blockNumber"),"transaction blockNumber")!=height:
        raise ValueError("transaction and receipt block height disagreement")
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
    gas_limit=hexint(tx.get("gas"),"transaction gas limit")
    gas_used=hexint(receipt.get("gasUsed"),"receipt gasUsed")
    effective_price=hexint(receipt.get("effectiveGasPrice"),"receipt effectiveGasPrice")
    if gas_limit<=0 or gas_used<=0 or gas_used>gas_limit or effective_price<=0:
        raise ValueError("invalid EVM gas usage or effective price")
    signed_price=hexint(tx.get("gasPrice"),"transaction gasPrice")
    if signed_price<=0 or effective_price>signed_price:
        raise ValueError("receipt effective price exceeds transaction gas price")
    return {"ok":True,"execution_succeeded":True,"evm_chain_id":actual_chain,"genesis_hash":genesis_hash,"tx_hash":tx_hash,
            "sender":sender,"recipient":recipient,"value_wei":str(amount_wei),
            "block_height":height,"block_hash":blockhash,"confirmations":latest-height+1,
            "gas_used":str(gas_used),"effective_gas_price_wei":str(effective_price),
            "gross_gas_paid_wei":str(gas_used*effective_price),
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
