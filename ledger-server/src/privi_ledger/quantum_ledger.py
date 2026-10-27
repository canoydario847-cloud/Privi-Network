"""Privi Quantum Ledger: the quantum-sealed block layer of Privi Ledger, fused with the Privi Foundation chain.

Privi Ledger already keeps per-stream SHA-256 hash chains and one RFC 9162 transparency log
(Privi Fortress). The Quantum Ledger turns that log into a chain of blocks:

  * Each block commits to the signed tree head of the transparency log at that moment
    (tree size + Merkle root), to the previous block, and to the entries it adds.
  * Blocks are hashed with SHA3-512 (FIPS 202). A quantum computer running Grover's search
    only halves hash security, so SHA3-512 keeps 256-bit security in the quantum era.
  * Every block is co-signed with ML-DSA-87 (NIST FIPS 204, CNSA 2.0) and Ed25519, using the
    same keys as Privi Fortress, so a future quantum computer cannot forge Privi's history.
  * Consecutive blocks are linked by RFC 9162 consistency proofs: the log only ever grew.
  * Blocks are fused with the Privi Foundation chain (Cosmos SDK + CometBFT + Cosmos EVM,
    production-network/ in this repo). Each block names the Foundation chain IDs it settles to
    and, when PRIVI_FOUNDATION_RPC_URL points at a Foundation node, carries a witness of that
    chain's latest block (height + hash), cross-linking the two ledgers. Until the Foundation
    mainnet launches, blocks are settled on Base through Privi Anchor.

This is an engineering design, not a certification (FIPS 140-3 validation, FedRAMP, DoD IL).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .fortress import Fortress, FortressError, canonical, leaf_hash, sha256_hex

GENESIS_PREV = "0" * 128
BLOCK_HASH_ALG = "SHA3-512 (FIPS 202) over canonical JSON (sorted keys, no spaces)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS qblocks (
    height INTEGER PRIMARY KEY, block_hash TEXT NOT NULL UNIQUE, signing_digest TEXT NOT NULL,
    body TEXT NOT NULL, ed25519 TEXT NOT NULL, ml_dsa_87 TEXT NOT NULL, anchor TEXT, created_at TEXT NOT NULL);
"""


def sha3_512_hex(s: str | bytes) -> str:
    return hashlib.sha3_512(s.encode("utf-8") if isinstance(s, str) else s).hexdigest()


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class QuantumLedgerError(Exception):
    pass


def foundation_profile() -> dict[str, Any]:
    """The Privi Foundation chain this ledger is fused with (see production-network/README.md)."""
    evm = os.getenv("PRIVI_FOUNDATION_EVM_CHAIN_ID", "262144").strip()
    return {
        "name": "Privi Foundation",
        "stack": "Cosmos SDK + CometBFT + Cosmos EVM",
        "cosmos_chain_id": os.getenv("PRIVI_FOUNDATION_COSMOS_CHAIN_ID", "local-4221").strip(),
        "evm_chain_id": int(evm) if evm.isdigit() else evm,
        "stage": os.getenv("PRIVI_FOUNDATION_STAGE", "pre-mainnet").strip(),
        "settlement_until_mainnet": "Base (via Privi Anchor)",
    }


def _rpc(url: str, method: str, params: list, timeout: float) -> Any:
    req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                       "params": params}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    if out.get("error"):
        raise QuantumLedgerError(str(out["error"]))
    return out.get("result")


def foundation_witness(url: str | None = None, timeout: float = 5.0) -> dict[str, Any] | None:
    """Latest block of the Privi Foundation chain over its EVM JSON-RPC, or None when not configured."""
    url = (url if url is not None else os.getenv("PRIVI_FOUNDATION_RPC_URL", "")).strip()
    if not url:
        return None
    try:
        blk = _rpc(url, "eth_getBlockByNumber", ["latest", False], timeout)
        cid = _rpc(url, "eth_chainId", [], timeout)
        return {"evm_chain_id": int(cid, 16), "height": int(blk["number"], 16), "block_hash": blk["hash"],
                "observed_at": _iso()}
    except Exception as e:  # the Foundation node being down must never stop the ledger
        return {"unavailable": True, "reason": f"{type(e).__name__}: {e}"[:200]}


class QuantumLedger:
    def __init__(self, ledger, fortress: Fortress, witness=foundation_witness):
        self.ledger, self.fortress = ledger, fortress
        self._db, self._lock = ledger._db, ledger._lock
        self._seal_lock = threading.Lock()
        self._witness = witness
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # ---------------- blocks ----------------

    @staticmethod
    def _row(r) -> dict[str, Any]:
        return {"block": json.loads(r["body"]), "block_hash": r["block_hash"], "signing_digest": r["signing_digest"],
                "signatures": {"ed25519": r["ed25519"], "ml_dsa_87": r["ml_dsa_87"]},
                "settlement": json.loads(r["anchor"]) if r["anchor"] else None}

    def latest(self) -> dict[str, Any] | None:
        r = self._db.execute("SELECT * FROM qblocks ORDER BY height DESC LIMIT 1").fetchone()
        return self._row(r) if r else None

    def block(self, height: int) -> dict[str, Any] | None:
        r = self._db.execute("SELECT * FROM qblocks WHERE height=?", (int(height),)).fetchone()
        return self._row(r) if r else None

    def height(self) -> int:
        r = self._db.execute("SELECT MAX(height) FROM qblocks").fetchone()
        return -1 if r[0] is None else r[0]

    def _entries_root(self, lo: int, hi: int) -> str:
        """SHA3-512 over the entry hashes this block adds (log indexes lo..hi-1), in recording order."""
        rows = self._db.execute("SELECT entry_hash FROM entries ORDER BY id LIMIT ? OFFSET ?", (hi - lo, lo)).fetchall()
        return sha3_512_hex("".join(r["entry_hash"] for r in rows))

    def seal(self, force: bool = False) -> dict[str, Any] | None:
        """Seal a new block if the log grew since the last one (or always, for the genesis block / force).
        Returns the new block, or None when there was nothing to seal."""
        with self._seal_lock:
            prev = self.latest()
            sth = self.fortress.tree_head()
            n = sth["tree_head"]["tree_size"]
            prev_size = prev["block"]["tree_size"] if prev else 0
            if prev and n == prev_size and not force:
                return None
            height = prev["block"]["height"] + 1 if prev else 0
            body = {
                "type": "PriviQuantumBlock", "version": "1", "ledger": "Privi Quantum Ledger",
                "height": height, "prev_block_hash": prev["block_hash"] if prev else GENESIS_PREV,
                "time": _iso(), "tree_size": n, "log_root": sth["tree_head"]["root_hash"],
                "tree_head_hash": sth["body_hash"], "new_entries": n - prev_size,
                "entries_root_sha3_512": self._entries_root(prev_size, n),
                "foundation": foundation_profile(), "foundation_witness": self._witness(),
                "block_hash_algorithm": BLOCK_HASH_ALG,
                "signatures": "Ed25519 + ML-DSA-87 over SHA-256(block_hash bytes)",
            }
            bh = sha3_512_hex(canonical(body))
            digest = sha256_hex(bytes.fromhex(bh))
            sig = self.fortress.cosign(digest, "quantum_block")
            with self._lock:
                self._db.execute("INSERT INTO qblocks VALUES (?,?,?,?,?,?,NULL,?)",
                                 (height, bh, digest, canonical(body), sig["ed25519"], sig["ml_dsa_87"], _iso()))
                self._db.commit()
            return self.block(height)

    def set_settlement(self, height: int, att: dict) -> None:
        with self._lock:
            self._db.execute("UPDATE qblocks SET anchor=? WHERE height=?", (json.dumps(att), height))
            self._db.commit()

    def unsettled(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM qblocks WHERE anchor IS NULL ORDER BY height LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT height, block_hash, body, anchor IS NOT NULL AS settled FROM qblocks "
                                "ORDER BY height DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            b = json.loads(r["body"])
            out.append({"height": r["height"], "block_hash": r["block_hash"], "time": b["time"],
                        "tree_size": b["tree_size"], "new_entries": b["new_entries"], "settled": bool(r["settled"])})
        return out

    # ---------------- verification ----------------

    def check_block(self, rec: dict[str, Any], prev: dict[str, Any] | None, deep: bool = True) -> list[str]:
        """Problems with one block (empty list = valid)."""
        b, problems = rec["block"], []
        bh = sha3_512_hex(canonical(b))
        if bh != rec["block_hash"]:
            problems.append("block contents were edited (SHA3-512 mismatch)")
        if sha256_hex(bytes.fromhex(rec["block_hash"])) != rec["signing_digest"]:
            problems.append("signing digest does not match the block hash")
        d, s = rec["signing_digest"], rec["signatures"]
        if not self.fortress.passports.signature_ok(d, s["ed25519"]):
            problems.append("Ed25519 signature invalid")
        if not self.fortress.pq_ok(d, s["ml_dsa_87"]):
            problems.append("ML-DSA-87 (post-quantum) signature invalid")
        if prev is None:
            if b["height"] != 0 or b["prev_block_hash"] != GENESIS_PREV:
                problems.append("first block is not a genesis block")
        else:
            if b["height"] != prev["block"]["height"] + 1:
                problems.append("height does not follow the previous block")
            if b["prev_block_hash"] != prev["block_hash"]:
                problems.append("not linked to the previous block")
            if b["tree_size"] < prev["block"]["tree_size"]:
                problems.append("transparency log shrank")
        if deep:
            sth = self.fortress.sth_at(b["tree_size"])
            if not sth or sth["tree_head"]["root_hash"] != b["log_root"] or sth["body_hash"] != b["tree_head_hash"]:
                problems.append("log root does not match the signed tree head")
            lo = prev["block"]["tree_size"] if prev else 0
            if self._entries_root(lo, b["tree_size"]) != b["entries_root_sha3_512"]:
                problems.append("entries in this block were changed, removed or reordered")
            if prev and 0 < lo < b["tree_size"]:
                try:
                    if not self.fortress.consistency(lo, b["tree_size"])["verified_here"]:
                        problems.append("consistency proof from the previous block failed (history rewritten)")
                except FortressError as e:
                    problems.append(f"consistency proof unavailable: {e}")
        return problems

    def verify_chain(self, deep_last: int = 50) -> dict[str, Any]:
        """Check every block's hash, link and both signatures; re-derive log roots, entry roots and
        consistency proofs for the most recent `deep_last` blocks."""
        rows = self._db.execute("SELECT * FROM qblocks ORDER BY height").fetchall()
        total, prev = len(rows), None
        for i, r in enumerate(rows):
            rec = self._row(r)
            problems = self.check_block(rec, prev, deep=i >= total - max(0, deep_last))
            if problems:
                return {"valid": False, "blocks": total, "broken_at_height": rec["block"]["height"], "problems": problems}
            prev = rec
        return {"valid": True, "blocks": total, "height": prev["block"]["height"] if prev else None,
                "head_hash": prev["block_hash"] if prev else None, "deep_checked_blocks": min(total, max(0, deep_last)),
                "checks": ["SHA3-512 block hashes", "hash links", "Ed25519 + ML-DSA-87 signatures",
                           "log roots vs signed tree heads", "SHA3-512 entry roots", "RFC 9162 consistency proofs"]}

    def entry_proof(self, entry_hash: str) -> dict[str, Any]:
        """Which quantum block holds an entry, with its Merkle inclusion proof into that block's log root."""
        h = (entry_hash or "").strip().lower().removeprefix("0x")
        row = self._db.execute("SELECT id FROM entries WHERE entry_hash=?", (h,)).fetchone()
        if not row:
            raise QuantumLedgerError("no entry with this hash")
        index = self._db.execute("SELECT COUNT(*) FROM entries WHERE id < ?", (row["id"],)).fetchone()[0]
        r = self._db.execute("SELECT * FROM qblocks WHERE json_extract(body, '$.tree_size') > ? ORDER BY height LIMIT 1",
                             (index,)).fetchone()
        if not r:
            return {"entry_hash": h, "sealed": False, "reason": "recorded after the latest block; it is sealed in the next block"}
        rec = self._row(r)
        inc = self.fortress.inclusion(h, rec["block"]["tree_size"])
        return {"entry_hash": h, "sealed": True, "block": rec, "inclusion": inc,
                "valid": inc["verified_here"] and not self.check_block(rec, self.block(rec["block"]["height"] - 1),
                                                                      deep=False)}

    def status(self) -> dict[str, Any]:
        head = self.latest()
        return {"ledger": "Privi Quantum Ledger", "height": head["block"]["height"] if head else None,
                "head": head, "pending_entries": self.fortress.size() - (head["block"]["tree_size"] if head else 0),
                "foundation": foundation_profile(),
                "foundation_rpc_configured": bool(os.getenv("PRIVI_FOUNDATION_RPC_URL", "").strip()),
                "keys": self.fortress.keys(), "block_hash_algorithm": BLOCK_HASH_ALG, "recent": self.recent(10)}

    # ---------------- Privi Quantum Scan (public explorer data) ----------------
    # Only hashes and counts are exposed here: never an organization, stream or entry content.

    def _sizes(self) -> list[tuple[int, int]]:
        rows = self._db.execute("SELECT height, json_extract(body,'$.tree_size') AS n FROM qblocks ORDER BY height").fetchall()
        return [(r["height"], r["n"]) for r in rows]

    @staticmethod
    def _height_for_index(sizes: list[tuple[int, int]], index: int) -> int | None:
        for h, n in sizes:
            if index < n:
                return h
        return None

    def scan_stats(self) -> dict[str, Any]:
        head = self.latest()
        settled = self._db.execute("SELECT COUNT(*) FROM qblocks WHERE anchor IS NOT NULL").fetchone()[0]
        entries = self.fortress.size()
        return {"blocks": self.height() + 1, "entries": entries, "settled_blocks": settled,
                "sealed_entries": head["block"]["tree_size"] if head else 0,
                "head_height": head["block"]["height"] if head else None,
                "head_hash": head["block_hash"] if head else None, "head_time": head["block"]["time"] if head else None,
                "foundation": foundation_profile(), "block_hash_algorithm": BLOCK_HASH_ALG,
                "signatures": "Ed25519 + ML-DSA-87 (FIPS 204)", "keys": self.fortress.keys()}

    def scan_blocks(self, limit: int = 25, before: int | None = None) -> dict[str, Any]:
        """Newest-first block summaries; pass the last height shown as `before` for the next page."""
        limit = max(1, min(int(limit), 100))
        cond, args = ("WHERE height < ?", (int(before), limit)) if before is not None else ("", (limit,))
        rows = self._db.execute(f"SELECT * FROM qblocks {cond} ORDER BY height DESC LIMIT ?", args).fetchall()
        out = []
        for r in rows:
            b, st = json.loads(r["body"]), json.loads(r["anchor"]) if r["anchor"] else None
            out.append({"height": r["height"], "block_hash": r["block_hash"], "prev_block_hash": b["prev_block_hash"],
                        "time": b["time"], "tree_size": b["tree_size"], "new_entries": b["new_entries"],
                        "log_root": b["log_root"], "tree_head_hash": b["tree_head_hash"],
                        "entries_root_sha3_512": b["entries_root_sha3_512"], "signing_digest": r["signing_digest"],
                        "settled": bool(st), "tx_hash": st["tx_hash"] if st else None,
                        "settlement_block": st.get("block_number") if st else None})
        nxt = out[-1]["height"] if len(out) == limit and out[-1]["height"] > 0 else None
        return {"blocks": out, "next_before": nxt}

    def scan_block(self, height: int) -> dict[str, Any] | None:
        rec = self.block(height)
        if not rec:
            return None
        prev = self.block(height - 1) if height else None
        problems = self.check_block(rec, prev)
        lo = prev["block"]["tree_size"] if prev else 0
        return {**rec, "valid": not problems, "problems": problems, "first_entry_index": lo,
                "last_entry_index": rec["block"]["tree_size"] - 1,
                "signature_sizes": {"ed25519_bytes": len(rec["signatures"]["ed25519"]) // 2,
                                    "ml_dsa_87_bytes": len(rec["signatures"]["ml_dsa_87"]) // 2}}

    def scan_entries(self, limit: int = 50, offset: int = 0, block: int | None = None) -> dict[str, Any]:
        """Entry receipt hashes in recording order (newest first unless a block is given). No contents, no org ids."""
        limit = max(1, min(int(limit), 100))
        sizes = self._sizes()
        total = self.fortress.size()
        if block is not None:
            rec = self.block(int(block))
            if not rec:
                raise QuantumLedgerError("no block at that height")
            prev = self.block(int(block) - 1) if block else None
            lo, hi = (prev["block"]["tree_size"] if prev else 0), rec["block"]["tree_size"]
        else:
            lo, hi = 0, total
        top = hi - max(0, int(offset))
        start = max(lo, top - limit)
        if top <= lo:
            return {"entries": [], "total": hi - lo, "range": [lo, hi]}
        rows = self._db.execute("SELECT entry_hash FROM entries ORDER BY id LIMIT ? OFFSET ?", (top - start, start)).fetchall()
        out = [{"index": start + i, "entry_hash": r["entry_hash"], "leaf_hash": leaf_hash(r["entry_hash"]).hex(),
                "block": self._height_for_index(sizes, start + i)} for i, r in enumerate(rows)]
        out.reverse()
        return {"entries": out, "total": hi - lo, "range": [lo, hi], "unsealed_from": sizes[-1][1] if sizes else 0}

    def scan_search(self, q: str) -> dict[str, Any]:
        """Find a block height or any hash this ledger holds."""
        q = (q or "").strip().lower().removeprefix("0x")
        if not q:
            return {"matches": []}
        m: list[dict[str, Any]] = []
        if q.isdigit() and len(q) < 10:
            if self.block(int(q)):
                m.append({"kind": "block_height", "height": int(q)})
        if len(q) in (64, 128) and all(c in "0123456789abcdef" for c in q):
            for r in self._db.execute("SELECT height FROM qblocks WHERE block_hash=?", (q,)):
                m.append({"kind": "block_hash", "height": r["height"]})
            for col, kind in (("signing_digest", "signing_digest"), ("json_extract(body,'$.tree_head_hash')", "tree_head_hash"),
                              ("json_extract(body,'$.log_root')", "log_root"),
                              ("json_extract(body,'$.entries_root_sha3_512')", "entries_root"),
                              ("json_extract(body,'$.prev_block_hash')", "previous_block_hash"),
                              ("json_extract(anchor,'$.tx_hash')", "settlement_tx")):
                for r in self._db.execute(f"SELECT height FROM qblocks WHERE {col}=? OR {col}=?", (q, "0x" + q)):
                    m.append({"kind": kind, "height": r["height"]})
            row = self._db.execute("SELECT id FROM entries WHERE entry_hash=?", (q,)).fetchone()
            if row:
                idx = self._db.execute("SELECT COUNT(*) FROM entries WHERE id < ?", (row["id"],)).fetchone()[0]
                m.append({"kind": "entry_hash", "index": idx, "height": self._height_for_index(self._sizes(), idx)})
            for r in (self._db.execute("SELECT entry_hash FROM entries") if len(q) == 64 else []):
                if leaf_hash(r["entry_hash"]).hex() == q:
                    m.append({"kind": "leaf_hash", "entry_hash": r["entry_hash"]})
                    break
        return {"query": q, "matches": m}
