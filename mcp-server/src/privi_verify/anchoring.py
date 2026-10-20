"""On-chain checkpoints through Privi Anchor.

Periodically takes the latest fingerprint ("head") of every chain of records that
changed and anchors those heads on the Privi blockchain with Privi Anchor. Once a
head is anchored, nobody (Privi included) can rewrite history up to that point
without the mismatch showing: an audit compares the anchored head with the
record at the same position.

This module is shared, file-for-file, by Privi Ledger and Privi Verify.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    chain_key    TEXT NOT NULL,     -- which record chain (stream or lot)
    seq          INTEGER NOT NULL,  -- position of the anchored head
    head_hash    TEXT NOT NULL,
    merkle_root  TEXT NOT NULL,
    tx_hash      TEXT NOT NULL,
    proof        TEXT NOT NULL,
    status       TEXT NOT NULL,     -- confirmed | pending
    block_number INTEGER,
    block_time   INTEGER,
    anchored_at  TEXT NOT NULL,
    PRIMARY KEY (chain_key, seq)
);
"""

MAX_PER_CALL = 100


class AnchorError(RuntimeError):
    pass


class AnchorClient(Protocol):
    def anchor(self, hashes: list[str], label: str) -> dict: ...


class HttpAnchorClient:
    """Calls the Privi Anchor MCP server's anchor_hashes tool over Streamable HTTP (JSON mode)."""

    def __init__(self, url: str, api_key: str, timeout: float = 90.0):
        self.url, self.api_key, self.timeout = url, api_key, timeout

    def anchor(self, hashes: list[str], label: str) -> dict:
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "anchor_hashes", "arguments": {"hashes": hashes, "label": label}}}
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST", headers={
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18", "Authorization": f"Bearer {self.api_key}"})
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
            raise AnchorError(sc.get("error") or "anchor_hashes failed")
        return sc


class Checkpoints:
    def __init__(self, db: sqlite3.Connection, lock: threading.Lock):
        self._db, self._lock = db, lock
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def anchored(self, chain_key: str, seq: int) -> bool:
        return self._db.execute("SELECT 1 FROM checkpoints WHERE chain_key=? AND seq=?",
                                (chain_key, seq)).fetchone() is not None

    def latest(self, chain_key: str) -> dict | None:
        r = self._db.execute("SELECT * FROM checkpoints WHERE chain_key=? ORDER BY seq DESC LIMIT 1",
                             (chain_key,)).fetchone()
        if not r:
            return None
        d = {k: r[k] for k in r.keys()}
        d["proof"] = json.loads(d["proof"])
        return d

    def save(self, chain_key: str, seq: int, head_hash: str, receipt: dict, result: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?,?,?,?,?,?,?)",
                (chain_key, seq, head_hash, result["merkle_root"], result["tx_hash"], json.dumps(receipt["proof"]),
                 result.get("status", "pending"), result.get("block_number"), result.get("block_time"),
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
            self._db.commit()

    def run_once(self, heads: Iterable[tuple[str, int, str]], client: AnchorClient, label: str) -> int:
        """Anchor every head not yet anchored. heads: (chain_key, seq, head_hash). Returns heads anchored."""
        todo = [h for h in heads if not self.anchored(h[0], h[1])]
        done = 0
        for i in range(0, len(todo), MAX_PER_CALL):
            chunk = todo[i:i + MAX_PER_CALL]
            result = client.anchor([h[2] for h in chunk], f"{label} checkpoint ({len(chunk)})")
            by_hash = {r["hash"]: r for r in result.get("receipts", [])}
            for key, seq, head in chunk:
                rcpt = by_hash.get(head.lower().removeprefix("0x"))
                if rcpt:
                    self.save(key, seq, head, rcpt, result)
                    done += 1
        return done


def describe(cp: dict | None, current_hash_at_seq: str | None, anchor_mcp_url: str) -> dict:
    """Checkpoint info for audit results. current_hash_at_seq is the record's hash at the anchored position now."""
    if not cp:
        return {"anchored": False, "note": "not anchored on chain yet; checkpoints run every few minutes"}
    return {
        "anchored": True, "seq": cp["seq"], "head_hash": cp["head_hash"],
        "matches_current_record": current_hash_at_seq == cp["head_hash"],
        "tx_hash": cp["tx_hash"], "merkle_root": cp["merkle_root"], "proof": cp["proof"],
        "block_number": cp["block_number"], "block_time": cp["block_time"], "status": cp["status"],
        "anchored_at": cp["anchored_at"],
        "verify_with": {"server": anchor_mcp_url, "tool": "anchor_verify",
                        "arguments": {"hash": cp["head_hash"], "tx_hash": cp["tx_hash"], "proof": cp["proof"]}},
    }


def start_loop(run: Callable[[], int], interval_s: float, name: str) -> threading.Thread:
    def loop():
        time.sleep(15)
        while True:
            try:
                n = run()
                if n:
                    print(f"{name}: anchored {n} checkpoint(s) on chain", flush=True)
            except Exception as e:  # keep serving; retry next round
                print(f"{name}: checkpoint error: {e}", flush=True)
            time.sleep(interval_s)
    t = threading.Thread(target=loop, daemon=True, name=f"{name}-checkpoints")
    t.start()
    return t
