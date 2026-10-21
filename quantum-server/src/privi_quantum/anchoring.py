# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Anchor attestation hashes on chain (Base) through Privi Anchor.

A background loop batches every not-yet-anchored attestation (up to 100 per
transaction) into one Privi Anchor call. The on-chain record fixes WHEN a result
existed; the ML-DSA-87 signature fixes WHO issued it. Even if a quantum computer
later breaks the chain's ECDSA keys, the signed body and its hash chain still
prove the result was not altered.
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


def anchor_pending(attestor, client, limit: int = 100) -> int:
    """Anchor every attestation that has no anchor yet. Returns how many were anchored."""
    rows = attestor._db.execute(
        "SELECT id, body_sha256 FROM attestations WHERE anchor IS NULL ORDER BY created_at LIMIT ?", (limit,)).fetchall()
    if not rows:
        return 0
    result = client.anchor([r["body_sha256"] for r in rows], f"Privi Quantum attestations ({len(rows)})")
    by_hash = {r["hash"]: r for r in result.get("receipts", [])}
    done = 0
    for r in rows:
        rc = by_hash.get(r["body_sha256"])
        if rc:
            attestor.set_anchor(r["id"], {
                "chain_id": result.get("chain_id"), "network": result.get("network"),
                "tx_hash": result.get("tx_hash"), "merkle_root": result.get("merkle_root"),
                "proof": rc.get("proof", []), "status": result.get("status"),
                "block_number": result.get("block_number"), "block_time": result.get("block_time"),
                "anchored_at": int(time.time())})
            done += 1
    return done
