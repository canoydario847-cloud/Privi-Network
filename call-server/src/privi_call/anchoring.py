# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Call - https://priviflow.us - dariocanoy@priviflow.us
"""Anchor the call log head on chain (Base) through Privi Anchor.

Every few minutes the hash at the head of the call log is anchored in one
Privi Anchor transaction. Because every call record is chained to the one
before it, one on-chain checkpoint proves the whole log up to that point.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class AnchorError(RuntimeError):
    pass


class HttpAnchorClient:
    """Calls the Privi Anchor MCP server over Streamable HTTP (JSON mode)."""

    def __init__(self, url: str, api_key: str = "", timeout: float = 90.0):
        self.url, self.api_key, self.timeout = url, api_key, timeout

    def anchor(self, hashes: list[str], label: str) -> dict:
        return self._call("anchor_hashes", {"hashes": hashes, "label": label})

    def verify(self, hash_hex: str, tx_hash: str, proof: list[str]) -> dict:
        return self._call("anchor_verify", {"hash": hash_hex, "tx_hash": tx_hash, "proof": proof})

    def _call(self, tool: str, arguments: dict) -> dict:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": "2025-06-18"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                text = r.read().decode()
        except (urllib.error.URLError, TimeoutError) as e:
            raise AnchorError(f"anchor request failed: {e}") from e
        if text.lstrip().startswith(("event:", "data:")):
            text = next(l[5:] for l in text.splitlines() if l.startswith("data:"))
        msg = json.loads(text)
        if "error" in msg:
            raise AnchorError(str(msg["error"]))
        res = msg["result"]
        sc = res.get("structuredContent") or {}
        if res.get("isError"):
            raise AnchorError(sc.get("error") or f"{tool} failed")
        return sc
