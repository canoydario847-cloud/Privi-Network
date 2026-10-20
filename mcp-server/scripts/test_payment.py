"""Make one real x402 test payment to a Privi Verify server, the way an AI agent would.

Uses a throwaway wallet on Base Sepolia testnet. No real money.

  pip install eth-account
  python scripts/test_payment.py --new-wallet        # 1. make a test wallet, prints its address
  # 2. get free testnet USDC: https://faucet.circle.com  (network: Base Sepolia, paste the address)
  python scripts/test_payment.py                      # 3. pay $0.01 and verify DEMO-STEEL-0001

The wallet's key is saved to .agent-wallet (git-ignored). It only holds faucet USDC;
never put real funds in it or reuse the key anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://privi-verify-production.up.railway.app/mcp"
WALLET_FILE = Path(".agent-wallet")
CHAIN_IDS = {"eip155:84532": 84532, "eip155:8453": 8453}
EXPLORERS = {"eip155:84532": "https://sepolia.basescan.org/tx/", "eip155:8453": "https://basescan.org/tx/"}


def mcp_call(url: str, method: str, params: dict, rid: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = resp.read().decode()
    if body.lstrip().startswith("event:") or body.lstrip().startswith("data:"):
        body = next(l[5:] for l in body.splitlines() if l.startswith("data:"))
    msg = json.loads(body)
    if "error" in msg:
        sys.exit(f"MCP error: {msg['error']}")
    return msg["result"]


def payment_required(result: dict) -> dict | None:
    sc = result.get("structuredContent")
    if not (isinstance(sc, dict) and "accepts" in sc):
        try:
            sc = json.loads(result["content"][0]["text"])
        except (KeyError, IndexError, ValueError):
            return None
    return sc if result.get("isError") and isinstance(sc, dict) and "accepts" in sc else None


def sign_payment(account, required: dict) -> dict:
    """Sign a USDC transferWithAuthorization (EIP-3009) for the first accepted option."""
    req = required["accepts"][0]
    if req["scheme"] != "exact" or req["network"] not in CHAIN_IDS:
        sys.exit(f"unsupported payment option: {req['scheme']} on {req['network']}")
    now = int(time.time())
    auth = {
        "from": account.address,
        "to": req["payTo"],
        "value": int(req["amount"]),
        "validAfter": now - 600,
        "validBefore": now + int(req.get("maxTimeoutSeconds", 60)),
        "nonce": bytes.fromhex(secrets.token_hex(32)),
    }
    signed = account.sign_typed_data(
        domain_data={
            "name": req["extra"]["name"],
            "version": req["extra"]["version"],
            "chainId": CHAIN_IDS[req["network"]],
            "verifyingContract": req["asset"],
        },
        message_types={
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ]
        },
        message_data=auth,
    )
    sig = signed.signature.hex()
    return {
        "x402Version": required["x402Version"],
        "resource": required.get("resource"),
        "accepted": req,
        "payload": {
            "signature": sig if sig.startswith("0x") else "0x" + sig,
            "authorization": {
                "from": auth["from"],
                "to": auth["to"],
                "value": str(auth["value"]),
                "validAfter": str(auth["validAfter"]),
                "validBefore": str(auth["validBefore"]),
                "nonce": "0x" + auth["nonce"].hex(),
            },
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=DEFAULT_URL, help="MCP endpoint")
    p.add_argument("--tool", default="privi_verify_lot", choices=["privi_verify_lot", "privi_chain_of_custody"])
    p.add_argument("--lot", default="DEMO-STEEL-0001")
    p.add_argument("--new-wallet", action="store_true", help="create a throwaway test wallet and exit")
    p.add_argument("--allow-mainnet", action="store_true", help="permit paying with real USDC on Base mainnet")
    args = p.parse_args()

    try:
        from eth_account import Account
    except ImportError:
        sys.exit("Install the signer first:  pip install eth-account")

    if args.new_wallet:
        if WALLET_FILE.exists():
            sys.exit(f"{WALLET_FILE} already exists (address {Account.from_key(WALLET_FILE.read_text().strip()).address})")
        acct = Account.create()
        WALLET_FILE.write_text(acct.key.hex())
        os.chmod(WALLET_FILE, 0o600)
        print(f"Test wallet address: {acct.address}")
        print("Next: https://faucet.circle.com -> Base Sepolia -> paste the address above, then run this script again.")
        return

    key = os.getenv("AGENT_PRIVATE_KEY") or (WALLET_FILE.read_text().strip() if WALLET_FILE.exists() else "")
    if not key:
        sys.exit("No wallet. Run with --new-wallet first.")
    account = Account.from_key(key)
    print(f"Agent wallet: {account.address}")

    mcp_call(args.url, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "privi-test-payment", "version": "1"},
    }, 1)

    call = {"name": args.tool, "arguments": {"lot_code": args.lot}}
    first = mcp_call(args.url, "tools/call", call, 2)
    required = payment_required(first)
    if not required:
        print("No payment was requested (payments may be disabled). Result:")
        print(json.dumps(first.get("structuredContent", first), indent=2))
        return

    opt = required["accepts"][0]
    usd = int(opt["amount"]) / 1_000_000
    print(f"Server asks ${usd:.2f} USDC on {opt['network']} to {opt['payTo']}")
    if opt["network"] == "eip155:8453" and not args.allow_mainnet:
        sys.exit("This server wants REAL USDC on Base mainnet. Re-run with --allow-mainnet if you mean it.")

    payment = sign_payment(account, required)
    second = mcp_call(args.url, "tools/call", {**call, "_meta": {"x402/payment": payment}}, 3)

    if second.get("isError"):
        err = (second.get("structuredContent") or {}).get("error") or second.get("content")
        sys.exit(f"Payment not accepted: {err}")

    receipt = (second.get("_meta") or {}).get("x402/payment-response", {})
    print("\nPaid. Result:")
    print(json.dumps(second.get("structuredContent"), indent=2))
    if receipt.get("transaction"):
        print(f"\nTransaction: {EXPLORERS.get(receipt.get('network'), '')}{receipt['transaction']}")


if __name__ == "__main__":
    main()
