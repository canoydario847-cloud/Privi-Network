#!/usr/bin/env python3
"""Read-only EVM wallet/RPC compatibility smoke check for disposable TEST devnets.

No keys, signing, eth_sendTransaction, eth_sendRawTransaction or real tokens.
Read-only RPC availability does NOT prove that a wallet can sign/spend funds.
"""
import argparse
import json
import re
import sys

from evm_smoke import RPC

QUANTITY = re.compile(r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$")
DATA = re.compile(r"^0x(?:[0-9a-fA-F]{2})*$")
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
# This fixed probe address is NOT a funded/controlled user address.
PROBE_ADDRESS = "0x000000000000000000000000000000000000dEaD"


def quantity(value, label):
    if not isinstance(value, str) or QUANTITY.fullmatch(value) is None:
        raise ValueError(f"{label}: invalid JSON-RPC quantity")
    return int(value, 16)


def check(rpc, expected_chain, address=PROBE_ADDRESS):
    if not isinstance(expected_chain, int) or isinstance(expected_chain, bool) or expected_chain <= 0:
        raise ValueError("expected chain ID must be positive integer")
    if expected_chain in (1, 56, 97):
        raise ValueError("refusing to probe known production/non-disposable EVM network IDs")
    if not isinstance(address, str) or ADDRESS.fullmatch(address) is None:
        raise ValueError("invalid 20-byte EVM probe address")

    observed_chain = quantity(rpc.call("eth_chainId"), "eth_chainId")
    if observed_chain != expected_chain:
        raise ValueError(f"EVM chain ID mismatch: expected {expected_chain}, observed {observed_chain}")

    height = quantity(rpc.call("eth_blockNumber"), "eth_blockNumber")
    if height < 1:
        raise ValueError("EVM chain has not produced blocks")
    # Pin subsequent reads to one historical block height for consistency.
    block = rpc.call("eth_getBlockByNumber", [hex(height), False])
    if not isinstance(block, dict) or not isinstance(block.get("hash"), str) or not HASH.fullmatch(block["hash"]):
        raise ValueError("historical block hash unavailable/invalid")
    if quantity(block.get("number"), "historical block number") != height:
        raise ValueError("historical block number mismatch")

    block_tag = hex(height)
    balance = quantity(rpc.call("eth_getBalance", [address, block_tag]), "eth_getBalance")
    nonce = quantity(rpc.call("eth_getTransactionCount", [address, block_tag]), "eth_getTransactionCount")
    code = rpc.call("eth_getCode", [address, block_tag])
    if not isinstance(code, str) or not DATA.fullmatch(code):
        raise ValueError("eth_getCode returned invalid EVM hex data")
    gas_price = quantity(rpc.call("eth_gasPrice"), "eth_gasPrice")
    if gas_price < 0:
        raise ValueError("gas price negative")
    return {
        "status": "READ_ONLY_WALLET_RPC_CHECKS_PASSED",
        "evm_chain_id": observed_chain,
        "block_height": height,
        "block_hash": block["hash"],
        "probe_address": address,
        "probe_balance_wei": str(balance),
        "probe_transaction_count": nonce,
        "probe_has_contract_code": len(code) > 2,
        "gas_price_wei": str(gas_price),
        "methods_checked": ["eth_chainId", "eth_blockNumber", "eth_getBlockByNumber",
                            "eth_getBalance", "eth_getTransactionCount", "eth_getCode",
                            "eth_gasPrice"],
        "limitations": "No signed transactions, balance-changing transfers, chain fee economics, signing wallets, or real public validator infrastructure were tested"
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rpc", default="http://127.0.0.1:8545")
    p.add_argument("--expect-chain", type=int, required=True)
    p.add_argument("--address", default=PROBE_ADDRESS)
    args = p.parse_args()
    # Explicit fixed local target by default. Non-loopback only when
    # operator has intentionally provided an RPC URL for a reviewed TESTnet.
    try:
        print(json.dumps({"ok": True, **check(RPC(args.rpc), args.expect_chain, args.address)}, indent=2))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
