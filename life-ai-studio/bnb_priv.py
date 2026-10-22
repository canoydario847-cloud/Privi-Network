"""Privi World Co — BNB Chain PRIV BEP-20 payment verification.

Separate from an as-yet-unverified native PRVI financial mainnet.
Payments are OFF by default and forbidden on disposable staging.
Copyright (c) 2026 Privi World Co. Third-party token code not claimed.
"""
import hashlib
import os
import re
from dataclasses import dataclass

from eth_utils import keccak

ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
HASH = re.compile(r"0x[0-9a-fA-F]{64}\Z")
TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
TRANSFER_SELECTOR = "0xa9059cbb"
CHAIN_ID = 56


@dataclass(frozen=True)
class Config:
    rpc_url: str
    contract: str
    treasury: str
    code_sha256: str
    token_decimals: int
    units_per_credit: int
    confirmations: int


class InvalidPayment(ValueError):
    pass


def configured(staging=False, secure_cookie=False):
    """Fail closed until token, actual merchant treasury, price and code are vetted."""
    if staging or not secure_cookie or os.getenv("BNB_PRIV_PAYMENTS_ENABLED") != "1":
        return None
    try:
        rpc_url = os.environ["BNB_PRIV_RPC_URL"]
        contract = os.environ["BNB_PRIV_TOKEN_ADDRESS"].lower()
        treasury = os.environ["BNB_PRIV_TREASURY_ADDRESS"].lower()
        digest = os.environ["BNB_PRIV_CODE_SHA256"].lower()
        decimals = int(os.environ["BNB_PRIV_DECIMALS"])
        unit = int(os.environ["BNB_PRIV_UNITS_PER_CREDIT"])
        conf = int(os.getenv("BNB_PRIV_REQUIRED_CONFIRMATIONS", "12"))
        if (not rpc_url.startswith("https://") or "@" in rpc_url
            or not ADDRESS.fullmatch(contract)
            or not ADDRESS.fullmatch(treasury) or int(contract, 16) == 0
            or int(treasury, 16) == 0 or treasury == contract
            or not HASH.fullmatch("0x" + digest)
            or not 0 <= decimals <= 36 or unit <= 0 or unit >= 10**50
            or conf < 12):
            return None
        return Config(rpc_url, contract, treasury, digest, decimals, unit, conf)
    except (KeyError, ValueError):
        return None


def _hexint(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value):
        raise InvalidPayment("Malformed RPC hexadecimal quantity")
    return int(value, 16)


def _topic_address(address):
    return "0x" + "0" * 24 + address[2:].lower()


def calldata(to, amount):
    """Exact calldata for ERC-20 transfer(address,uint256)."""
    if not ADDRESS.fullmatch(to) or amount <= 0 or amount >= 2**256:
        raise ValueError("Invalid transfer request")
    return TRANSFER_SELECTOR + to[2:].lower().rjust(64, "0") + format(amount, "064x")


async def validate_contract(cfg, rpc):
    if _hexint(await rpc(cfg.rpc_url, "eth_chainId", [])) != CHAIN_ID:
        raise InvalidPayment("RPC is not BNB Chain mainnet")
    code = await rpc(cfg.rpc_url, "eth_getCode", [cfg.contract, "latest"])
    if not isinstance(code, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", code):
        raise InvalidPayment("Token contract has no runtime bytecode")
    if hashlib.sha256(bytes.fromhex(code[2:])).hexdigest() != cfg.code_sha256:
        raise InvalidPayment("Token runtime bytecode fingerprint mismatch")
    data = await rpc(cfg.rpc_url, "eth_call",
                     [{"to": cfg.contract, "data": "0x313ce567"}, "latest"])
    if _hexint(data) != cfg.token_decimals:
        raise InvalidPayment("Token decimals mismatch")
    return True


async def verify_transfer(cfg, quote, tx_hash, rpc):
    if not HASH.fullmatch(tx_hash):
        raise InvalidPayment("Invalid transaction hash")
    await validate_contract(cfg, rpc)
    tx = await rpc(cfg.rpc_url, "eth_getTransactionByHash", [tx_hash])
    receipt = await rpc(cfg.rpc_url, "eth_getTransactionReceipt", [tx_hash])
    if not isinstance(tx, dict) or not isinstance(receipt, dict):
        raise InvalidPayment("Missing mined transaction and receipt")
    if not tx.get("blockNumber") or not receipt.get("blockNumber"):
        raise InvalidPayment("Transaction is not confirmed")
    expected_data = calldata(cfg.treasury, int(quote["amount_units"]))
    if (tx.get("from", "").lower() != quote["wallet"].lower()
        or tx.get("to", "").lower() != cfg.contract
        or (tx.get("input") or "").lower() != expected_data
        or _hexint(tx.get("value", "0x0")) != 0
        or _hexint(receipt.get("status", "0x0")) != 1
        or receipt.get("transactionHash", "").lower() != tx_hash.lower()
        or receipt.get("blockHash") != tx.get("blockHash")
        or tx.get("blockNumber") != receipt.get("blockNumber")):
        raise InvalidPayment("Transfer sender, contract, calldata or receipt differs")
    block = await rpc(cfg.rpc_url, "eth_getBlockByNumber",
                      [tx["blockNumber"], False])
    tip = _hexint(await rpc(cfg.rpc_url, "eth_blockNumber", []))
    if (not isinstance(block, dict) or block.get("hash") != tx.get("blockHash")
        or tip - _hexint(receipt["blockNumber"]) + 1 < cfg.confirmations
        or _hexint(block.get("timestamp", "0x0")) < quote["created"] - 30
        or _hexint(block.get("timestamp", "0x0")) > quote["expires"] + 300):
        raise InvalidPayment("Block is stale, not canonical, or not final enough")
    logs = receipt.get("logs", [])
    if not isinstance(logs, list) or len(logs) > 10000:
        raise InvalidPayment("Invalid transaction logs")
    matched = False
    for log in logs:
        if not isinstance(log, dict):
            continue
        topics = log.get("topics", [])
        if (log.get("address", "").lower() != cfg.contract or len(topics) != 3
            or topics[0].lower() != TRANSFER_TOPIC
            or topics[1].lower() != _topic_address(quote["wallet"])
            or topics[2].lower() != _topic_address(cfg.treasury)):
            continue
        if _hexint(log.get("data", "0x0")) == int(quote["amount_units"]):
            matched = True
            break
    if not matched:
        raise InvalidPayment("Exact token transfer event not found")
    return {"contract": cfg.contract, "treasury": cfg.treasury,
            "chain_id": CHAIN_ID, "tx_hash": tx_hash.lower(),
            "amount_units": quote["amount_units"], "confirmations": cfg.confirmations}
