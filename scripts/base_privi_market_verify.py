#!/usr/bin/env python3
"""Read-only Base mainnet evidence for project-declared PRIVI contract and swap desk.

Does not buy/sell, create a pool, send transactions, sign, or require private keys.
This probes no Uniswap v4 pools and proves nothing about regulatory status.
Copyright (c) 2026 Privi World Co. All rights reserved.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RPC_URL = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
TOKEN = "0xA11626baF87524e61B5697634C7Ec48D26279D6C".lower()
DESK = "0x59d0fd923242e30e48c0d5486410c3c4039785e1"
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WETH = "0x4200000000000000000000000000000000000006"
UNISWAP_V3_FACTORY = "0x33128a8fc17869897dce68ed026d694621f6fdfd"
AERODROME_FACTORY = "0x420dd381b31aef6683db6b902084cb0ffece40da"

SEL = {
    "name": "06fdde03", "symbol": "95d89b41", "decimals": "313ce567",
    "totalSupply": "18160ddd", "balanceOf": "70a08231",
    "desk_base": "cbd11194", "desk_quote": "11eac855", "desk_price": "10bace8c",
    "desk_scale": "c2ee3a08", "desk_paused": "5c975abb",
    "uni_pool": "1698ee82", "aero_pool": "79bc57d5",
}


def rpc(method: str, params: list) -> object:
    request = Request(
        RPC_URL,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "privi-public-market-verifier/1"},
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=16) as response:
                body = json.load(response)
            if "error" in body:
                raise RuntimeError(f"RPC {method}: {body['error']}")
            if not isinstance(body.get("result"), (str, dict)):
                raise RuntimeError(f"RPC {method}: missing result")
            return body["result"]
        except (OSError, HTTPError, URLError, TimeoutError) as error:
            if attempt == 2:
                raise RuntimeError(f"RPC {method} unavailable: {type(error).__name__}") from error
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def calldata_address(address: str) -> str:
    return address.lower().removeprefix("0x").rjust(64, "0")


def uint(value: str) -> int:
    if not value or value == "0x":
        raise RuntimeError("Contract returned an empty value")
    return int(value, 16)


def eth_call(address: str, data: str) -> str:
    result = rpc("eth_call", [{"to": address, "data": "0x" + data}, "latest"])
    if not isinstance(result, str):
        raise RuntimeError("Invalid eth_call result")
    return result


def field_u(address: str, selector: str) -> int:
    return uint(eth_call(address, selector))


def field_addr(address: str, selector: str) -> str:
    data = eth_call(address, selector).removeprefix("0x")
    if len(data) < 64:
        raise RuntimeError("Contract returned a malformed address")
    return "0x" + data[-40:].lower()


def field_str(address: str, selector: str) -> str:
    data = bytes.fromhex(eth_call(address, selector).removeprefix("0x"))
    if len(data) == 32:  # Legacy bytes32-returning ERC-20 implementations
        return data.rstrip(b"\x00").decode("utf-8", "replace")
    if len(data) < 64:
        raise RuntimeError("Invalid dynamic ABI string")
    offset = int.from_bytes(data[:32], "big")
    if offset + 32 > len(data):
        raise RuntimeError("String offset is outside contract return value")
    length = int.from_bytes(data[offset:offset + 32], "big")
    if length > 512 or offset + 32 + length > len(data):
        raise RuntimeError("Unreasonable or malformed string length")
    return data[offset + 32:offset + 32 + length].decode("utf-8", "replace")


def balance(asset: str, owner: str) -> int:
    return field_u(asset, SEL["balanceOf"] + calldata_address(owner))


def discover_v3_aero() -> list[dict]:
    pools = []
    for other, label in [(USDC, "USDC"), (WETH, "WETH")]:
        for fee in (100, 500, 3000, 10000):
            result = field_addr(UNISWAP_V3_FACTORY, SEL["uni_pool"] +
                                calldata_address(TOKEN) + calldata_address(other) +
                                format(fee, "064x"))
            if int(result, 16):
                pools.append({"venue": "Uniswap v3", "pair": "PRIVI/" + label,
                              "fee_pips": fee, "pool": result,
                              "privi_balance_raw": str(balance(TOKEN, result))})
        for stable in (0, 1):
            result = field_addr(AERODROME_FACTORY, SEL["aero_pool"] +
                                calldata_address(TOKEN) + calldata_address(other) +
                                format(stable, "064x"))
            if int(result, 16):
                pools.append({"venue": "Aerodrome classic", "pair": "PRIVI/" + label,
                              "stable": bool(stable), "pool": result,
                              "privi_balance_raw": str(balance(TOKEN, result))})
    return pools


def main() -> int:
    report: dict = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "network": "Base mainnet",
        "chain_id_expected": 8453,
        "token_address": TOKEN,
        "desk_address": DESK,
        "warning": "Read-only chain state, not token approval, audit, price assurance, market depth, trade execution, investment advice or listing confirmation.",
        "dex_coverage": "Selected Uniswap v3 and Aerodrome classic pairs only; excludes Uniswap v4, Aerodrome Slipstream and direct swap desk fill tests",
    }
    try:
        chain = uint(str(rpc("eth_chainId", [])))
        report["chain_id"] = chain
        if chain != 8453:
            raise RuntimeError(f"RPC is on incorrect chain {chain}")
        report["block_number"] = uint(str(rpc("eth_blockNumber", [])))
        for address, label in ((TOKEN, "token"), (DESK, "swap_desk")):
            code = str(rpc("eth_getCode", [address, "latest"]))
            report[label + "_deployed"] = code not in ("0x", "0x0", "")
        if not report["token_deployed"]:
            raise RuntimeError("PRIVI token has no code at the declared address on this Base RPC")
        report["token_onchain"] = {
            "name": field_str(TOKEN, SEL["name"]),
            "symbol": field_str(TOKEN, SEL["symbol"]),
            "decimals": field_u(TOKEN, SEL["decimals"]),
            "total_supply_raw": str(field_u(TOKEN, SEL["totalSupply"])),
        }
        if report["swap_desk_deployed"]:
            try:
                scale = field_u(DESK, SEL["desk_scale"]) or 10**18
                price = field_u(DESK, SEL["desk_price"])
                d = {
                    "base_token": field_addr(DESK, SEL["desk_base"]),
                    "quote_token": field_addr(DESK, SEL["desk_quote"]),
                    "paused": bool(field_u(DESK, SEL["desk_paused"])),
                    "price_usdc_per_privi": str(price / scale),
                    "privi_available_raw": str(balance(TOKEN, DESK)),
                    "usdc_available_raw": str(balance(USDC, DESK)),
                }
                d["contract_pair_matches"] = d["base_token"] == TOKEN and d["quote_token"] == USDC
                report["swap_desk"] = d
            except Exception as error:
                report["swap_desk_error"] = str(error)
        try:
            report["selected_pools"] = discover_v3_aero()
        except Exception as error:
            report["selected_pools_error"] = str(error)
        report["ok"] = True
    except Exception as error:
        report["ok"] = False
        report["error"] = str(error)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
