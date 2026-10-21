# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Post-quantum attestations: every result Privi Quantum returns is signed twice.

Ed25519 (classical) + ML-DSA-87 (NIST FIPS 204, the CNSA 2.0 parameter set), over
the canonical JSON body. Both must verify. A future quantum computer that breaks
Ed25519 still cannot forge a Privi Quantum result, and the body hash is anchored
on the Privi chain so the time it was issued is fixed too.

Keys are deterministic from two 32-byte seeds (env QUANTUM_SIGNING_SEED as 128 hex
chars, or generated once and kept in the database on the persistent disk).
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import mldsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PQ_ALG = "ML-DSA-87 (NIST FIPS 204, CNSA 2.0)"
CTX = b"privi-quantum-attestation-v1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS signing_keys (key_id TEXT PRIMARY KEY, seeds_hex TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attestations (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, body_sha256 TEXT NOT NULL,
    ed25519 TEXT NOT NULL, ml_dsa_87 TEXT NOT NULL, key_id TEXT NOT NULL, anchor TEXT, created_at TEXT NOT NULL);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


class Attestor:
    def __init__(self, db_path: str, seeds_hex: str = ""):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        seeds_hex = "".join(seeds_hex.split())
        if not seeds_hex:
            r = self._db.execute("SELECT seeds_hex FROM signing_keys ORDER BY created_at LIMIT 1").fetchone()
            seeds_hex = r["seeds_hex"] if r else secrets.token_hex(64)
        if len(seeds_hex) != 128:
            raise ValueError("QUANTUM_SIGNING_SEED must be 128 hex characters (two 32-byte seeds)")
        raw = bytes.fromhex(seeds_hex)
        self._ed = Ed25519PrivateKey.from_private_bytes(raw[:32])
        self._pq = mldsa.MLDSA87PrivateKey.from_seed_bytes(raw[32:])
        self.ed_pub = self._ed.public_key().public_bytes_raw()
        self.pq_pub = self._pq.public_key().public_bytes_raw()
        self.key_id = "pq_" + hashlib.sha256(self.ed_pub + self.pq_pub).hexdigest()[:16]
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO signing_keys VALUES (?,?,?)", (self.key_id, seeds_hex, now_iso()))
            self._db.commit()

    def public_keys(self) -> dict[str, Any]:
        return {"key_id": self.key_id, "ed25519": b64(self.ed_pub), "ml_dsa_87": b64(self.pq_pub),
                "ml_dsa_context": CTX.decode(), "pq_algorithm": PQ_ALG,
                "signed_message": "canonical JSON of body (sorted keys, no spaces, UTF-8)"}

    def issue(self, kind: str, body: dict) -> dict:
        aid = "qa_" + secrets.token_hex(8)
        body = {"attestation_id": aid, "kind": kind, "issuer": "Privi Quantum (Privi World Co)",
                "issued_at": now_iso(), **body}
        msg = canonical(body)
        att = {"id": aid, "body": body, "body_sha256": hashlib.sha256(msg).hexdigest(),
               "signatures": {"ed25519": b64(self._ed.sign(msg)), "ml_dsa_87": b64(self._pq.sign(msg, CTX))},
               "key_id": self.key_id, "anchor": None}
        with self._lock:
            self._db.execute("INSERT INTO attestations VALUES (?,?,?,?,?,?,?,?,?)",
                             (aid, kind, json.dumps(body), att["body_sha256"], att["signatures"]["ed25519"],
                              att["signatures"]["ml_dsa_87"], self.key_id, None, body["issued_at"]))
            self._db.commit()
        return att

    def set_anchor(self, aid: str, anchor: dict) -> None:
        with self._lock:
            self._db.execute("UPDATE attestations SET anchor=? WHERE id=?", (json.dumps(anchor), aid))
            self._db.commit()

    def get(self, aid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM attestations WHERE id=?", (aid,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "body": json.loads(r["body"]), "body_sha256": r["body_sha256"],
                "signatures": {"ed25519": r["ed25519"], "ml_dsa_87": r["ml_dsa_87"]},
                "key_id": r["key_id"], "anchor": json.loads(r["anchor"]) if r["anchor"] else None}

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM attestations").fetchone()[0]

    @staticmethod
    def verify(att: dict, ed_pub_b64: str, pq_pub_b64: str) -> dict:
        """Check both signatures and the body hash. Works offline with the published keys."""
        try:
            body, sigs = att["body"], att["signatures"]
            msg = canonical(body)
            ed_ok = pq_ok = False
            try:
                Ed25519PublicKey.from_public_bytes(base64.b64decode(ed_pub_b64)).verify(base64.b64decode(sigs["ed25519"]), msg)
                ed_ok = True
            except InvalidSignature:
                pass
            try:
                mldsa.MLDSA87PublicKey.from_public_bytes(base64.b64decode(pq_pub_b64)).verify(
                    base64.b64decode(sigs["ml_dsa_87"]), msg, CTX)
                pq_ok = True
            except InvalidSignature:
                pass
            hash_ok = hashlib.sha256(msg).hexdigest() == att.get("body_sha256")
        except (KeyError, TypeError, ValueError) as e:
            return {"valid": False, "reason": f"malformed attestation: {e}"}
        out = {"valid": ed_ok and pq_ok and hash_ok, "ed25519_valid": ed_ok, "ml_dsa_87_valid": pq_ok,
               "body_hash_matches": hash_ok}
        if not out["valid"]:
            out["reason"] = "attestation was modified or not signed by this key"
        return out
