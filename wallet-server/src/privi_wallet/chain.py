"""Base (EVM) JSON-RPC: balances, and signing and sending ETH, PRIVI and USDC from custodial wallets."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Any, Callable

from .config import PRIVI_TOKEN, USDC_TOKEN

ASSETS = {
    "ETH": {"token": None, "decimals": 18},
    "PRIVI": {"token": PRIVI_TOKEN, "decimals": 18},
    "USDC": {"token": USDC_TOKEN, "decimals": 6},
}
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
SEL_BALANCE_OF = "70a08231"
SEL_TRANSFER = "a9059cbb"


class ChainError(RuntimeError):
    pass


def is_address(a: str) -> bool:
    return bool(ADDRESS_RE.match(a or ""))


def to_units(amount: Decimal, decimals: int) -> int:
    units = amount * (Decimal(10) ** decimals)
    if units != units.to_integral_value():
        raise ValueError(f"at most {decimals} decimal places")
    return int(units)


def from_units(units: int, decimals: int) -> str:
    d = Decimal(units) / (Decimal(10) ** decimals)
    s = format(d.normalize(), "f")
    return s


def _word(a: str) -> str:
    return a.lower().removeprefix("0x").rjust(64, "0")


def new_account() -> tuple[str, str]:
    """A fresh secp256k1 key from the OS random source. Returns (address, private_key_hex)."""
    from eth_account import Account
    acct = Account.create()
    key = acct.key.hex()
    return acct.address, key if key.startswith("0x") else "0x" + key


def eth_account_signer(private_key: str, tx: dict) -> str:
    from eth_account import Account
    from eth_utils import to_checksum_address   # installed with eth-account; it rejects lowercase "to" addresses
    tx = {**tx, "to": to_checksum_address(tx["to"])}
    signed = Account.from_key(private_key).sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    raw_hex = raw.hex() if isinstance(raw, (bytes, bytearray)) else str(raw)
    return raw_hex if raw_hex.startswith("0x") else "0x" + raw_hex


class Chain:
    def __init__(self, rpc_url: str, chain_id: int, rpc: Callable[[str, list], Any] | None = None,
                 signer: Callable[[str, dict], str] = eth_account_signer, timeout: float = 15.0):
        self.rpc_url, self.chain_id, self.timeout = rpc_url, chain_id, timeout
        self._rpc_fn = rpc
        self._sign = signer
        self._id = 0

    def rpc(self, method: str, params: list) -> Any:
        if self._rpc_fn:
            return self._rpc_fn(method, params)
        self._id += 1
        req = urllib.request.Request(
            self.rpc_url, method="POST", headers={"Content-Type": "application/json", "User-Agent": "privi-wallet/0.1"},
            data=json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}).encode())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                msg = json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise ChainError(f"{method}: {e}") from e
        if "error" in msg:
            raise ChainError(f"{method}: {msg['error'].get('message', msg['error'])}")
        return msg.get("result")

    def balance_units(self, asset: str, holder: str) -> int:
        token = ASSETS[asset]["token"]
        if token is None:
            return int(self.rpc("eth_getBalance", [holder, "latest"]), 16)
        out = self.rpc("eth_call", [{"to": token, "data": "0x" + SEL_BALANCE_OF + _word(holder)}, "latest"])
        return int(out or "0x0", 16)

    def balances(self, holder: str) -> dict[str, str]:
        return {a: from_units(self.balance_units(a, holder), ASSETS[a]["decimals"]) for a in ASSETS}

    def build_send(self, frm: str, asset: str, to: str, amount: Decimal) -> dict:
        """The unsigned transaction, after checking the wallet holds the amount plus gas."""
        if not is_address(to):
            raise ValueError("not a valid 0x address")
        if amount <= 0:
            raise ValueError("amount must be more than zero")
        to, frm = to.lower(), frm.lower()
        meta = ASSETS[asset]
        units = to_units(amount, meta["decimals"])
        if meta["token"] is None:
            call = {"from": frm, "to": to, "value": hex(units), "data": "0x"}
        else:
            call = {"from": frm, "to": meta["token"], "value": "0x0",
                    "data": "0x" + SEL_TRANSFER + _word(to) + hex(units)[2:].rjust(64, "0")}
        if self.balance_units(asset, frm) < units:
            raise ValueError(f"not enough {asset} in this wallet")
        gas_price = int(int(self.rpc("eth_gasPrice", []), 16) * 1.2) + 1
        try:
            gas = int(int(self.rpc("eth_estimateGas", [call]), 16) * 1.25)
        except ChainError as e:
            raise ValueError(f"the network rejected this transfer: {e}") from e
        eth = self.balance_units("ETH", frm)
        need = gas * gas_price + (units if meta["token"] is None else 0)
        if eth < need:
            raise ValueError("not enough ETH on Base in this wallet to pay the network fee "
                             f"(needs about {from_units(gas * gas_price, 18)} ETH)")
        nonce = int(self.rpc("eth_getTransactionCount", [frm, "pending"]), 16)
        return {"nonce": nonce, "gasPrice": gas_price, "gas": gas, "to": call["to"], "value": int(call["value"], 16),
                "data": call["data"], "chainId": self.chain_id}

    def send(self, private_key: str, tx: dict) -> str:
        return self.rpc("eth_sendRawTransaction", [self._sign(private_key, tx)])
