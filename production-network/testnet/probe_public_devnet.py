#!/usr/bin/env python3
"""Verify public Privi EVM HTTPS RPC and make ONE valueless signed TEST-coin transfer.

Use only upstream Cosmos EVM public development mnemonic generated into upstream
v0.7.3 testnet genesis. Never supply real keys, token contracts, or PRIV assets.
"""
import argparse
import json
import secrets
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

PUBLIC_DEMO_MNEMONIC = (
    "copper push brief egg scan entry inform record adjust fossil boss egg "
    "comic alien upon aspect dry avoid interest fury window hint race symptom"
)
EXPECTED_RPC = "https://privi-evm-devnet-development.up.railway.app/"
EXPECTED_ID = 262144


def rpc(method, params=None, endpoint=EXPECTED_RPC):
    request = Request(
        endpoint, data=json.dumps({"jsonrpc":"2.0","id":1,"method":method,
                                   "params":params or []}).encode(),
        headers={"Content-Type":"application/json", "User-Agent":"Privi-EVM-Public-RPC-Smoketest/1"},
        method="POST")
    with urlopen(request, timeout=16) as response:
        if response.status != 200:
            raise RuntimeError(f"{method} HTTP {response.status}")
        body = response.read(1024*1024)
    res = json.loads(body)
    if res.get("error") is not None:
        raise RuntimeError(f"{method} RPC error: {res['error']}")
    if "result" not in res:
        raise RuntimeError(f"{method} RPC result missing")
    return res["result"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--send-test", action="store_true", help="Broadcast exactly one one-wei valueless TEST transfer")
    args = p.parse_args()
    chain_id = int(rpc("eth_chainId"),16)
    if chain_id != EXPECTED_ID:
        raise RuntimeError(f"Wrong chain ID: got {chain_id} (0x{chain_id:x}); expected {EXPECTED_ID}")
    height = int(rpc("eth_blockNumber"),16)
    if height < 2:
        raise RuntimeError("Chain not producing blocks yet")
    block = rpc("eth_getBlockByNumber",[hex(height),False])
    if not block or not block.get("hash"):
        raise RuntimeError("Cannot retrieve latest Ethereum block")
    print(json.dumps({"rpc":EXPECTED_RPC,"chainId":chain_id,"chainIdHex":hex(chain_id),
                      "blockHeight":height,"blockHash":block["hash"]},indent=2),flush=True)

    if not args.send_test:
        print("Read-only RPC check passed; no transaction sent.",flush=True)
        return

    # Public fixture from upstream sources, *not* a secret, suitable ONLY for valueless developer chains.
    from eth_account import Account
    Account.enable_unaudited_hdwallet_features()
    sender = Account.from_mnemonic(PUBLIC_DEMO_MNEMONIC)
    receiver = Account.create(secrets.token_bytes(32))
    balance = int(rpc("eth_getBalance", [sender.address,"latest"]),16)
    gas_price = max(int(rpc("eth_gasPrice"),16), 10**9)
    nonce = int(rpc("eth_getTransactionCount",[sender.address,"pending"]),16)
    cost = (gas_price * 21000) + 1
    print(json.dumps({"sender":sender.address,"receiver":receiver.address,
                      "balanceWei":str(balance),"gasPriceWei":str(gas_price),
                      "nonce":nonce,"valueWei":"1"}),flush=True)
    if balance < cost:
        raise RuntimeError("Public upstream demo account not funded; no transaction broadcast")

    tx = {"type":0, "chainId":chain_id, "nonce":nonce, "to":receiver.address,
          "value":1, "gas":21000, "gasPrice":gas_price}
    signed = sender.sign_transaction(tx)
    # Do NOT display private keys, mnemonic-derived signing objects or raw transactions in logs.
    raw = signed.raw_transaction.hex()
    if not raw.startswith("0x"): raw="0x"+raw
    txhash = rpc("eth_sendRawTransaction", [raw])
    if not isinstance(txhash,str) or not txhash.startswith("0x"):
        raise RuntimeError("RPC returned invalid transaction hash")
    print("Broadcast TEST transfer transaction: "+txhash,flush=True)
    deadline = time.monotonic()+125
    receipt = None
    while time.monotonic()<deadline:
        receipt = rpc("eth_getTransactionReceipt",[txhash])
        if receipt: break
        time.sleep(5)
    if not receipt:
        raise RuntimeError("Test transaction submitted but no receipt within timeout")
    if int(receipt.get("status","0x0"),16)!=1:
        raise RuntimeError("Test transaction reverted: "+json.dumps(receipt))
    if receipt.get("to","").lower()!=receiver.address.lower():
        raise RuntimeError("Transaction receipt recipient mismatch")
    if int(rpc("eth_getBalance",[receiver.address,"latest"]),16)<1:
        raise RuntimeError("Destination did not receive expected valueless wei")
    print(json.dumps({"result":"PASS","txHash":txhash,
                      "receiptBlock":int(receipt["blockNumber"],16),
                      "gasUsed":int(receipt["gasUsed"],16),
                      "recipient":receiver.address,"testValueWei":1},indent=2),flush=True)

if __name__=="__main__":
    try:main()
    except Exception as e:
        print("PUBLIC RPC / TEST TRANSFER FAILED:",str(e),file=sys.stderr,flush=True)
        raise SystemExit(1) from e
