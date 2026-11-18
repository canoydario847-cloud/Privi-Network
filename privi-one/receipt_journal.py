"""Privi ONE sandbox-only SQLite receipt journal.

Atomic idempotent decisions and a hash-linked receipt sequence. The journal is
neither a Privi Ledger entry nor an independent cryptographic signature.
Render free-tier files are ephemeral; use durable, backed-up storage later.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import sqlite3
import threading
import time

SCHEMA = "privi-one-sandbox-journal-v1"
ZERO = "0" * 64

def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def digest(data):
    return hashlib.sha256(canonical(data)).hexdigest()

class Journal:
    def __init__(self, path):
        if not isinstance(path, str) or not path:
            raise ValueError("SQLite path required")
        self.path = path
        self._lock = threading.RLock()
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                receipt_hash TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(session_id, request_id)
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS receipts_created_at ON receipts(created_at)")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def run_once(self, session_id, request_id, payload, create, *, now=None):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("Invalid sandbox session")
        if (not isinstance(request_id, str) or not 8 <= len(request_id) <= 128
                or not all(c.isascii() and (c.isalnum() or c in "-_") for c in request_id)):
            raise ValueError("Invalid sandbox request ID")
        now = int(time.time()) if now is None else now
        request_hash = digest(payload)
        # SQLite serializes conflicting writers; process lock also prevents
        # duplicate work by concurrent threads in this instance.
        with self._lock:
            db = self._db()
            try:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT request_hash,receipt_json FROM receipts WHERE session_id=? AND request_id=?",
                    (session_id, request_id)).fetchone()
                if existing:
                    if not hmac.compare_digest(existing[0], request_hash):
                        raise ValueError("Conflicting request ID replay")
                    stored = db.execute(
                        "SELECT receipt_hash FROM receipts WHERE session_id=? AND request_id=?",
                        (session_id, request_id)).fetchone()
                    parsed = json.loads(existing[1])
                    if not hmac.compare_digest(digest(parsed), stored[0]):
                        raise RuntimeError("Stored receipt integrity failure")
                    db.commit()
                    return parsed, True
                previous = db.execute(
                    "SELECT entry_hash FROM receipts ORDER BY seq DESC LIMIT 1").fetchone()
                prev_hash = previous[0] if previous else ZERO
                result = create()
                receipt_hash = digest(result)
                entry = {
                    "schema": SCHEMA, "session": hashlib.sha256(session_id.encode()).hexdigest(),
                    "request_id": request_id, "request_hash": request_hash,
                    "receipt_hash": receipt_hash, "previous_hash": prev_hash, "created_at": now,
                }
                entry_hash = digest(entry)
                db.execute("""INSERT INTO receipts
                    (session_id,request_id,request_hash,receipt_json,receipt_hash,
                     prev_hash,entry_hash,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (session_id, request_id, request_hash, canonical(result).decode(),
                     receipt_hash, prev_hash, entry_hash, now))
                db.commit()
                return result, False
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def audit(self):
        """Verify stored receipt hashes and chain links; does not prove origin."""
        with self._lock:
            db = self._db()
            try:
                rows = db.execute(
                    """SELECT seq,session_id,request_id,request_hash,receipt_json,
                       receipt_hash,prev_hash,entry_hash,created_at
                       FROM receipts ORDER BY seq ASC""").fetchall()
            finally:
                db.close()
        previous = ZERO
        expected_seq = 1
        for row in rows:
            seq, session_id, request_id, request_hash, receipt_json, receipt_hash, prev_hash, entry_hash, created_at = row
            try:
                if seq != expected_seq:
                    return {"valid": False, "entries_checked": expected_seq - 1,
                            "reason": "missing_or_renumbered_entries"}
                result = json.loads(receipt_json)
                computed_receipt = digest(result)
                entry = {
                    "schema": SCHEMA, "session": hashlib.sha256(session_id.encode()).hexdigest(),
                    "request_id": request_id, "request_hash": request_hash,
                    "receipt_hash": receipt_hash, "previous_hash": prev_hash, "created_at": created_at,
                }
                valid = (hmac.compare_digest(computed_receipt, receipt_hash)
                         and hmac.compare_digest(prev_hash, previous)
                         and hmac.compare_digest(digest(entry), entry_hash))
            except (ValueError, TypeError, UnicodeError):
                valid = False
            if not valid:
                return {"valid": False, "entries_checked": seq, "reason": "hash_chain_mismatch"}
            previous = entry_hash
            expected_seq += 1
        return {"valid": True, "entries_checked": len(rows), "head": previous,
                "scope": "LOCAL_SQLITE_TAMPER_EVIDENCE_NOT_EXTERNAL_PROOF"}



def checkpoint(journal):
    """Return a snapshot for users to pin OUTSIDE the service."""
    result = journal.audit()
    if not result.get("valid"):
        raise RuntimeError("Journal integrity check failed")
    return {
        "schema": "privi-one-external-checkpoint-v1",
        "sequence": result["entries_checked"],
        "head": result["head"],
        "mode": "LOCAL_SANDBOX_UNSIGNED_CHECKPOINT",
    }


def check_pinned_checkpoint(journal, pinned):
    """Verify a previously saved external checkpoint against current history.

    The external checkpoint is *not* trusted just because it is downloaded
    from this server: callers must store/pin it independently BEFORE a
    later suspected tampering event. This detects truncation/rewrite *only*
    relative to a trusted checkpoint. No signature or external anchoring.
    """
    if not isinstance(pinned, dict) or set(pinned) != {
            "schema", "sequence", "head", "mode"}:
        return {"valid": False, "reason": "invalid_checkpoint"}
    seq = pinned["sequence"]
    if (pinned["schema"] != "privi-one-external-checkpoint-v1"
            or pinned["mode"] != "LOCAL_SANDBOX_UNSIGNED_CHECKPOINT"
            or type(seq) is not int or seq < 0
            or not isinstance(pinned["head"], str)
            or len(pinned["head"]) != 64):
        return {"valid": False, "reason": "invalid_checkpoint"}
    audit = journal.audit()
    if not audit.get("valid"):
        return {"valid": False, "reason": "journal_integrity_failure"}
    if seq > audit["entries_checked"]:
        return {"valid": False, "reason": "journal_truncated"}
    with journal._lock:
        db = journal._db()
        try:
            row = db.execute(
                "SELECT entry_hash FROM receipts WHERE seq=?", (seq,)
            ).fetchone() if seq else (ZERO,)
        finally:
            db.close()
    if row is None or not hmac.compare_digest(row[0], pinned["head"]):
        return {"valid": False, "reason": "checkpoint_mismatch"}
    return {"valid": True, "sequence": seq,
            "current_entries": audit["entries_checked"],
            "mode": "EXTERNALLY_PINNED_CHECKPOINT_REQUIRED"}
