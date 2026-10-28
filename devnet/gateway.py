"""Privi Devnet public gateway (stdlib only).

Serves, on $PORT:
  POST /  or /rpc        Ethereum JSON-RPC (eth_*, net_*, web3_* only), proxied to the local node
  GET  /health           200 when the node answers and is producing blocks
  GET  /api/status       chain id, latest block, block time
  GET  /api/block/<n>    block by number (or "latest")
  GET  /api/tx/<hash>    transaction + receipt (anchor transactions show their data payload)
  GET  /api/address/<a>  balance and nonce
  GET  /chain.json       EIP-3085 parameters to add the devnet to a wallet
  GET  / /tx/.. /block/.. /address/..   the explorer page
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

NODE = os.getenv("DEVNET_NODE_RPC", "http://127.0.0.1:8545")
PORT = int(os.getenv("PORT", "10000"))
PUBLIC_URL = os.getenv("DEVNET_PUBLIC_URL", "https://privi-devnet.onrender.com").rstrip("/")
EVM_ID = int(os.getenv("DEVNET_EVM_CHAIN_ID", "772626"))
COSMOS_ID = os.getenv("DEVNET_COSMOS_CHAIN_ID", "privi-devnet-1")
RATE_PER_MIN = int(os.getenv("DEVNET_RATE_PER_MIN", "600"))
WEB = Path(__file__).with_name("web")
ALLOWED = re.compile(r"^(eth_|net_|web3_)[A-Za-z]+$")
BLOCKED = {"eth_sign", "eth_signTransaction", "eth_sendTransaction", "eth_accounts", "eth_coinbase",
           "eth_mining", "eth_hashrate", "eth_submitWork", "eth_submitHashrate"}
STARTED = time.time()

_hits: dict[str, list[float]] = {}
_lock = threading.Lock()


def allow(ip: str) -> bool:
    now = time.time()
    with _lock:
        q = [t for t in _hits.get(ip, []) if now - t < 60]
        if len(q) >= RATE_PER_MIN:
            _hits[ip] = q
            return False
        q.append(now)
        _hits[ip] = q
        return True


def node_raw(body: bytes, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(NODE, data=body, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def rpc(method: str, params: list | None = None):
    out = json.loads(node_raw(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}).encode()))
    if "error" in out:
        raise RuntimeError(out["error"].get("message", str(out["error"])))
    return out.get("result")


def h2i(x):
    return int(x, 16) if isinstance(x, str) and x.startswith("0x") else x


def decode_text(data: str | None) -> str | None:
    """Anchor transactions carry a readable label or a 32-byte root; show text when it is text."""
    if not data or data == "0x":
        return None
    try:
        raw = bytes.fromhex(data[2:])
        txt = raw.decode("utf-8")
        if all(c.isprintable() or c in "\n\t" for c in txt):
            return txt
    except Exception:
        pass
    return None


def status() -> dict:
    head = rpc("eth_getBlockByNumber", ["latest", False])
    return {
        "network": "Privi Devnet",
        "evm_chain_id": h2i(rpc("eth_chainId")),
        "cosmos_chain_id": COSMOS_ID,
        "latest_block": h2i(head["number"]),
        "latest_block_time": h2i(head["timestamp"]),
        "seconds_since_block": int(time.time()) - h2i(head["timestamp"]),
        "gas_token": "TEST (valueless)",
        "rpc_url": PUBLIC_URL,
        "explorer": PUBLIC_URL,
        "engine": "Cosmos EVM v0.7.3 (evmd), single validator",
        "gateway_uptime_s": int(time.time() - STARTED),
    }


def chain_params() -> dict:
    return {"chainId": hex(EVM_ID), "chainName": "Privi Devnet",
            "nativeCurrency": {"name": "Privi Devnet Test", "symbol": "TEST", "decimals": 18},
            "rpcUrls": [PUBLIC_URL], "blockExplorerUrls": [PUBLIC_URL]}


class Handler(BaseHTTPRequestHandler):
    server_version = "PriviDevnet/1"

    def log_message(self, fmt, *args):  # quiet: Render keeps request logs
        pass

    def _ip(self) -> str:
        return (self.headers.get("x-forwarded-for") or self.client_address[0]).split(",")[0].strip()

    def _send(self, code: int, body: bytes, ctype: str = "application/json", cache: str = "no-store"):
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-headers", "content-type")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("cache-control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, indent=1).encode())

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_POST(self):
        if self.path not in ("/", "/rpc"):
            return self._json(404, {"error": "POST JSON-RPC to /"})
        if not allow(self._ip()):
            return self._json(429, {"jsonrpc": "2.0", "id": None, "error": {"code": -32005, "message": "rate limited"}})
        n = int(self.headers.get("content-length") or 0)
        if n <= 0 or n > 1_000_000:
            return self._json(413, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "bad request size"}})
        body = self.rfile.read(n)
        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            return self._json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
        calls = msg if isinstance(msg, list) else [msg]
        if len(calls) > 50:
            return self._json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "batch too large"}})
        for c in calls:
            m = c.get("method", "") if isinstance(c, dict) else ""
            if not ALLOWED.match(m) or m in BLOCKED:
                return self._json(200, {"jsonrpc": "2.0", "id": c.get("id") if isinstance(c, dict) else None,
                                        "error": {"code": -32601, "message": f"method not available on the public gateway: {m}"}})
        try:
            self._send(200, node_raw(body, timeout=30))
        except (urllib.error.URLError, TimeoutError) as e:
            self._json(503, {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": f"node unavailable: {e}"}})

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        try:
            if p == "/health":
                s = status()
                ok = s["evm_chain_id"] == EVM_ID and s["seconds_since_block"] < 120
                return self._json(200 if ok else 503, {"ok": ok, **s})
            if p == "/api/status":
                return self._json(200, status())
            if p == "/chain.json":
                return self._json(200, chain_params())
            m = re.fullmatch(r"/api/block/(latest|\d+)", p)
            if m:
                tag = m.group(1) if m.group(1) == "latest" else hex(int(m.group(1)))
                b = rpc("eth_getBlockByNumber", [tag, False])
                if not b:
                    return self._json(404, {"error": "block not found"})
                return self._json(200, {"number": h2i(b["number"]), "hash": b["hash"], "time": h2i(b["timestamp"]),
                                        "transactions": b["transactions"], "gas_used": h2i(b["gasUsed"])})
            m = re.fullmatch(r"/api/tx/(0x[0-9a-fA-F]{64})", p)
            if m:
                tx = rpc("eth_getTransactionByHash", [m.group(1)])
                if not tx:
                    return self._json(404, {"error": "transaction not found"})
                rc = rpc("eth_getTransactionReceipt", [m.group(1)]) or {}
                blk = rpc("eth_getBlockByNumber", [tx["blockNumber"], False]) if tx.get("blockNumber") else None
                return self._json(200, {
                    "hash": tx["hash"], "from": tx["from"], "to": tx.get("to"), "value_wei": str(h2i(tx["value"])),
                    "block": h2i(tx.get("blockNumber")), "time": h2i(blk["timestamp"]) if blk else None,
                    "status": ("success" if rc.get("status") == "0x1" else "failed") if rc else "pending",
                    "gas_used": h2i(rc.get("gasUsed")), "data": tx.get("input"), "data_text": decode_text(tx.get("input")),
                    "chain_id": EVM_ID})
            m = re.fullmatch(r"/api/address/(0x[0-9a-fA-F]{40})", p)
            if m:
                return self._json(200, {"address": m.group(1),
                                        "balance_wei": str(h2i(rpc("eth_getBalance", [m.group(1), "latest"]))),
                                        "nonce": h2i(rpc("eth_getTransactionCount", [m.group(1), "latest"]))})
            if p == "/" or re.fullmatch(r"/(tx|block|address)/[0-9a-zA-Zx]+", p):
                return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8", "public, max-age=300")
            return self._json(404, {"error": "not found"})
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            return self._json(503, {"ok": False, "error": f"node starting or unavailable: {e}"})
        except RuntimeError as e:
            return self._json(400, {"error": str(e)})


if __name__ == "__main__":
    print(f"[gateway] Privi Devnet gateway on :{PORT} -> {NODE}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
