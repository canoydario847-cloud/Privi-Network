"""Minimal EVM JSON-RPC client that signs and sends anchor transactions.

Anchors are zero-value transactions from the service wallet to itself, with the
anchor bytes in the data field. No smart contract is needed, so anchoring works
on any EVM chain and costs only intrinsic gas.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Protocol


class Chain(Protocol):
    chain_id: int
    address: str

    def send_data(self, data_hex: str) -> str: ...
    def receipt(self, tx_hash: str) -> dict | None: ...
    def transaction(self, tx_hash: str) -> dict | None: ...
    def block_timestamp(self, block_number: int) -> int | None: ...
    def latest_block(self) -> int: ...
    def balance_wei(self) -> int: ...


class RpcError(RuntimeError):
    pass


class JsonRpcChain:
    def __init__(self, rpc_url: str, chain_id: int, private_key: str, timeout: float = 20.0):
        from eth_account import Account  # imported lazily so read-only tooling works without it

        self.rpc_url, self.chain_id, self.timeout = rpc_url, chain_id, timeout
        self._acct = Account.from_key(private_key)
        self.address = self._acct.address
        self._lock = threading.Lock()
        self._id = 0
        self._next_nonce: int | None = None   # local view: some RPC nodes report a stale "pending" count

    def _rpc(self, method: str, params: list) -> Any:
        self._id += 1
        req = urllib.request.Request(
            self.rpc_url,
            data=json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                msg = json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise RpcError(f"{method}: {e}") from e
        if "error" in msg:
            raise RpcError(f"{method}: {msg['error'].get('message', msg['error'])}")
        return msg.get("result")

    def remote_chain_id(self) -> int:
        return int(self._rpc("eth_chainId", []), 16)

    def latest_block(self) -> int:
        return int(self._rpc("eth_blockNumber", []), 16)

    def balance_wei(self) -> int:
        return int(self._rpc("eth_getBalance", [self.address, "latest"]), 16)

    NONCE_ERRORS = ("underpriced", "nonce too low", "already known", "known transaction")

    def send_data(self, data_hex: str) -> str:
        with self._lock:  # one nonce at a time
            remote = int(self._rpc("eth_getTransactionCount", [self.address, "pending"]), 16)
            nonce = max(remote, self._next_nonce or 0)
            gas_price = int(self._rpc("eth_gasPrice", []), 16)
            tx = {"from": self.address, "to": self.address, "value": "0x0", "data": data_hex}
            try:
                gas = int(int(self._rpc("eth_estimateGas", [tx]), 16) * 1.3)
            except RpcError:
                gas = 21000 + 16 * (len(data_hex) // 2) + 10000
            for attempt in range(3):
                try:
                    h = self._rpc("eth_sendRawTransaction", [self._sign(nonce, gas_price, gas, data_hex)])
                    self._next_nonce = nonce + 1
                    return h
                except RpcError as e:
                    if attempt == 2 or not any(k in str(e).lower() for k in self.NONCE_ERRORS):
                        raise
                    nonce += 1          # that nonce is taken (our own earlier tx not yet visible): use the next one
            raise RpcError("eth_sendRawTransaction: could not find a free nonce")

    def _sign(self, nonce: int, gas_price: int, gas: int, data_hex: str) -> str:
        signed = self._acct.sign_transaction({
            "nonce": nonce, "gasPrice": int(gas_price * 1.2) + 1, "gas": gas,
            "to": self.address, "value": 0, "data": data_hex, "chainId": self.chain_id,
        })
        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        raw_hex = raw.hex() if isinstance(raw, (bytes, bytearray)) else str(raw)
        return raw_hex if raw_hex.startswith("0x") else "0x" + raw_hex

    def receipt(self, tx_hash: str) -> dict | None:
        return self._rpc("eth_getTransactionReceipt", [tx_hash])

    def transaction(self, tx_hash: str) -> dict | None:
        return self._rpc("eth_getTransactionByHash", [tx_hash])

    def block_timestamp(self, block_number: int) -> int | None:
        b = self._rpc("eth_getBlockByNumber", [hex(block_number), False])
        return int(b["timestamp"], 16) if b else None


def wait_receipt(chain: Chain, tx_hash: str, timeout_s: float = 25.0, poll_s: float = 1.5) -> dict | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = chain.receipt(tx_hash)
        if r:
            return r
        time.sleep(poll_s)
    return None
