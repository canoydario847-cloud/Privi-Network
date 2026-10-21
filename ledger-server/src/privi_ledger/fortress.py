"""Privi Fortress: defense-grade integrity controls for Privi Ledger.

1. Post-quantum co-signatures. Every Privi attestation (passports, compliance reports,
   mandates, tree heads, evidence bundles) is signed twice: Ed25519 (classical) and
   ML-DSA-87 (NIST FIPS 204, the parameter set CNSA 2.0 requires for national security
   systems), so a future quantum computer cannot forge Privi's history.

2. Transparency log. All entries from all organizations form one append-only Merkle
   tree (RFC 9162, the design behind Certificate Transparency). Signed tree heads,
   inclusion proofs ("this entry is in the log") and consistency proofs ("the log only
   grew; nothing was rewritten") can be checked by anyone, offline. Tree heads are
   anchored on chain (Base).

3. Two-Person Integrity. Sensitive actions need N distinct, wallet-signed approvals from
   a named set of officers before they are authorized; any officer can veto. The
   authorization is single-use and logged.

4. Air-gapped evidence bundles. A self-contained, dual-signed package (entries, chain
   check, inclusion proof, signed tree head, anchors, issuer keys) that the standalone
   verify_bundle.py checks with no network access.

These are engineering controls aligned with NIST SP 800-53 (AU-9, AU-10, AC-5, SC-13)
and CNSA 2.0. They are not a certification (FIPS 140-3 validation, FedRAMP, DoD IL).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric import mldsa

from .kya import checksum, norm_address, personal_hash, recover_address

PQ_ALG = "ML-DSA-87 (NIST FIPS 204, CNSA 2.0)"

SCHEMA = """
CREATE TABLE IF NOT EXISTS pq_keys (key_id TEXT PRIMARY KEY, seed_hex TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cosignatures (
    subject_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, ed25519 TEXT NOT NULL, ml_dsa_87 TEXT NOT NULL,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tree_heads (
    tree_size INTEGER PRIMARY KEY, root_hash TEXT NOT NULL, timestamp TEXT NOT NULL, body TEXT NOT NULL,
    body_hash TEXT NOT NULL, ed25519 TEXT NOT NULL, ml_dsa_87 TEXT NOT NULL, anchor TEXT);
CREATE TABLE IF NOT EXISTS tpi_policies (
    org_id TEXT NOT NULL, name TEXT NOT NULL, officers TEXT NOT NULL, required INTEGER NOT NULL,
    updated_at TEXT NOT NULL, PRIMARY KEY (org_id, name));
CREATE TABLE IF NOT EXISTS tpi_requests (
    request_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, policy TEXT NOT NULL, stream_id TEXT NOT NULL,
    summary TEXT NOT NULL, details_hash TEXT NOT NULL, officers TEXT NOT NULL, required INTEGER NOT NULL,
    status TEXT NOT NULL, approvals TEXT NOT NULL DEFAULT '[]', vetoed_by TEXT, created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL, decided_at TEXT, executed_at TEXT);
CREATE INDEX IF NOT EXISTS idx_tpi_org ON tpi_requests (org_id, created_at);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str | bytes) -> str:
    return hashlib.sha256(s.encode("utf-8") if isinstance(s, str) else s).hexdigest()


class FortressError(Exception):
    pass


# ---------------------------------------------------------------- RFC 9162 Merkle tree

def _h(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def leaf_hash(entry_hash_hex: str) -> bytes:
    return _h(b"\x00" + bytes.fromhex(entry_hash_hex))


def _k(n: int) -> int:
    k = 1
    while k * 2 < n:
        k *= 2
    return k


class _Tree:
    """Merkle tree over leaf hashes with memoized subtree roots (RFC 9162 section 2.1)."""

    def __init__(self, leaves: list[bytes]):
        self.leaves, self._memo = leaves, {}

    def mth(self, lo: int, hi: int) -> bytes:
        n = hi - lo
        if n == 0:
            return _h(b"")
        if n == 1:
            return self.leaves[lo]
        key = (lo, hi)
        if key not in self._memo:
            k = _k(n)
            self._memo[key] = _h(b"\x01" + self.mth(lo, lo + k) + self.mth(lo + k, hi))
        return self._memo[key]

    def path(self, m: int, lo: int, hi: int) -> list[bytes]:
        n = hi - lo
        if n <= 1:
            return []
        k = _k(n)
        if m < k:
            return self.path(m, lo, lo + k) + [self.mth(lo + k, hi)]
        return self.path(m - k, lo + k, hi) + [self.mth(lo, lo + k)]

    def subproof(self, m: int, lo: int, hi: int, b: bool) -> list[bytes]:
        n = hi - lo
        if m == n:
            return [] if b else [self.mth(lo, hi)]
        k = _k(n)
        if m <= k:
            return self.subproof(m, lo, lo + k, b) + [self.mth(lo + k, hi)]
        return self.subproof(m - k, lo + k, hi, False) + [self.mth(lo, lo + k)]


def verify_inclusion(leaf: bytes, index: int, size: int, path: list[bytes], root: bytes) -> bool:
    """RFC 9162 section 2.1.3.2."""
    if index >= size:
        return False
    fn, sn, r = index, size - 1, leaf
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = _h(b"\x01" + p + r)
            if not fn & 1:
                while True:
                    fn >>= 1
                    sn >>= 1
                    if fn & 1 or fn == 0:
                        break
        else:
            r = _h(b"\x01" + r + p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == root


def verify_consistency(first: int, second: int, root1: bytes, root2: bytes, proof: list[bytes]) -> bool:
    """RFC 9162 section 2.1.4.2."""
    if first == second:
        return not proof and root1 == root2
    if first == 0:
        return not proof
    if first > second or not proof:
        return False
    if first & (first - 1) == 0:
        proof = [root1] + proof
    fn, sn = first - 1, second - 1
    while fn & 1:
        fn >>= 1
        sn >>= 1
    fr = sr = proof[0]
    for c in proof[1:]:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            fr = _h(b"\x01" + c + fr)
            sr = _h(b"\x01" + c + sr)
            if not fn & 1:
                while True:
                    fn >>= 1
                    sn >>= 1
                    if fn & 1 or fn == 0:
                        break
        else:
            sr = _h(b"\x01" + sr + c)
        fn >>= 1
        sn >>= 1
    return sn == 0 and fr == root1 and sr == root2


# ---------------------------------------------------------------- Fortress

class Fortress:
    def __init__(self, ledger, passports, issuer_url: str, pq_seed_hex: str = ""):
        self.ledger, self._db, self._lock = ledger, ledger._db, ledger._lock
        self.passports, self.issuer_url = passports, issuer_url
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self._pq = self._load_pq(pq_seed_hex)
        self.pq_public_hex = self._pq.public_key().public_bytes_raw().hex()
        self.pq_key_id = "pqk_" + sha256_hex(bytes.fromhex(self.pq_public_hex))[:16]

    # ---------------- post-quantum signing ----------------

    def _load_pq(self, seed_hex: str):
        if seed_hex:
            return mldsa.MLDSA87PrivateKey.from_seed_bytes(bytes.fromhex(seed_hex.strip()))
        with self._lock:
            r = self._db.execute("SELECT seed_hex FROM pq_keys ORDER BY created_at LIMIT 1").fetchone()
            if r:
                return mldsa.MLDSA87PrivateKey.from_seed_bytes(bytes.fromhex(r["seed_hex"]))
            k = mldsa.MLDSA87PrivateKey.generate()
            self._db.execute("INSERT INTO pq_keys VALUES (?,?,?)", ("k1", k.private_bytes_raw().hex(), _iso(_now())))
            self._db.commit()
            return k

    def keys(self) -> dict:
        iss = self.passports.issuer()
        return {"classical": {"algorithm": "Ed25519", "key_id": iss["key_id"], "public_key_hex": iss["public_key_hex"]},
                "post_quantum": {"algorithm": PQ_ALG, "key_id": self.pq_key_id, "public_key_hex": self.pq_public_hex},
                "signing_input": "the 32 raw bytes of the SHA-256 subject hash"}

    def pq_sign(self, h: str) -> str:
        return self._pq.sign(bytes.fromhex(h)).hex()

    def pq_ok(self, h: str, sig_hex: str) -> bool:
        try:
            self._pq.public_key().verify(bytes.fromhex(sig_hex), bytes.fromhex(h))
            return True
        except Exception:
            return False

    def cosign(self, h: str, kind: str, store: bool = True) -> dict:
        """Ed25519 + ML-DSA-87 signatures over a SHA-256 subject hash."""
        with self._lock:
            r = self._db.execute("SELECT * FROM cosignatures WHERE subject_hash=?", (h,)).fetchone()
        if r:
            return {"subject_hash": h, "ed25519": r["ed25519"], "ml_dsa_87": r["ml_dsa_87"],
                    "key_ids": [self.passports.key_id, self.pq_key_id]}
        ed, pq = self.passports.sign(h), self.pq_sign(h)
        if store:
            with self._lock:
                self._db.execute("INSERT OR IGNORE INTO cosignatures VALUES (?,?,?,?,?)", (h, kind, ed, pq, _iso(_now())))
                self._db.commit()
        return {"subject_hash": h, "ed25519": ed, "ml_dsa_87": pq, "key_ids": [self.passports.key_id, self.pq_key_id]}

    def check_cosign(self, h: str) -> dict:
        r = self._db.execute("SELECT * FROM cosignatures WHERE subject_hash=?", (h,)).fetchone()
        if not r:
            return {"post_quantum_signed": False}
        return {"post_quantum_signed": True, "kind": r["kind"],
                "ed25519_valid": self.passports.signature_ok(h, r["ed25519"]),
                "ml_dsa_87_valid": self.pq_ok(h, r["ml_dsa_87"]), "ml_dsa_87_signature": r["ml_dsa_87"]}

    # ---------------- transparency log ----------------

    def _leaves(self, size: int | None = None) -> list[tuple[str, bytes]]:
        rows = self._db.execute("SELECT entry_hash FROM entries ORDER BY id" + (" LIMIT ?" if size else ""),
                                (size,) if size else ()).fetchall()
        return [(r["entry_hash"], leaf_hash(r["entry_hash"])) for r in rows]

    def size(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    def tree_head(self) -> dict:
        """Latest signed tree head; a new one is signed whenever the log has grown."""
        n = self.size()
        r = self._db.execute("SELECT * FROM tree_heads WHERE tree_size=?", (n,)).fetchone()
        if r:
            return self._sth_row(r)
        root = _Tree([l for _, l in self._leaves(n)]).mth(0, n).hex()
        body = {"type": "PriviTreeHead", "version": "1", "log": f"{self.issuer_url}/log", "tree_size": n,
                "root_hash": root, "timestamp": _iso(_now()), "hash_algorithm": "SHA-256",
                "tree": "RFC 9162 Merkle tree over SHA-256(0x00 || entry_hash) in recording order"}
        bh = sha256_hex(canonical(body))
        ed, pq = self.passports.sign(bh), self.pq_sign(bh)
        with self._lock:
            self._db.execute("INSERT OR IGNORE INTO tree_heads VALUES (?,?,?,?,?,?,?,NULL)",
                             (n, root, body["timestamp"], canonical(body), bh, ed, pq))
            self._db.commit()
        return self._sth_row(self._db.execute("SELECT * FROM tree_heads WHERE tree_size=?", (n,)).fetchone())

    def sth_at(self, size: int) -> dict | None:
        r = self._db.execute("SELECT * FROM tree_heads WHERE tree_size=?", (size,)).fetchone()
        return self._sth_row(r) if r else None

    def set_sth_anchor(self, size: int, att: dict) -> None:
        with self._lock:
            self._db.execute("UPDATE tree_heads SET anchor=? WHERE tree_size=?", (json.dumps(att), size))
            self._db.commit()

    def last_anchored_sth(self) -> dict | None:
        r = self._db.execute("SELECT * FROM tree_heads WHERE anchor IS NOT NULL ORDER BY tree_size DESC LIMIT 1").fetchone()
        return self._sth_row(r) if r else None

    @staticmethod
    def _sth_row(r) -> dict:
        return {"tree_head": json.loads(r["body"]), "body_hash": r["body_hash"],
                "signatures": {"ed25519": r["ed25519"], "ml_dsa_87": r["ml_dsa_87"]},
                "anchor": json.loads(r["anchor"]) if r["anchor"] else None}

    def inclusion(self, entry_hash: str, tree_size: int | None = None) -> dict:
        h = (entry_hash or "").strip().lower().removeprefix("0x")
        row = self._db.execute("SELECT id FROM entries WHERE entry_hash=?", (h,)).fetchone()
        if not row:
            raise FortressError("no entry with this hash")
        index = self._db.execute("SELECT COUNT(*) FROM entries WHERE id < ?", (row["id"],)).fetchone()[0]
        sth = self.tree_head() if tree_size is None else self.sth_at(tree_size)
        if not sth:
            raise FortressError("no signed tree head for that size; omit tree_size to use the latest")
        n = sth["tree_head"]["tree_size"]
        if index >= n:
            raise FortressError("entry is newer than that tree head")
        tree = _Tree([l for _, l in self._leaves(n)])
        path = tree.path(index, 0, n)
        return {"entry_hash": h, "leaf_index": index, "tree_size": n, "leaf_hash": leaf_hash(h).hex(),
                "audit_path": [p.hex() for p in path], "signed_tree_head": sth,
                "verified_here": verify_inclusion(leaf_hash(h), index, n, path, bytes.fromhex(sth["tree_head"]["root_hash"]))}

    def consistency(self, first: int, second: int | None = None) -> dict:
        new = self.tree_head() if second is None else self.sth_at(second)
        old = self.sth_at(first)
        if not new or not old:
            raise FortressError("both sizes must have signed tree heads (see ledger_tree_head history)")
        a, b = old["tree_head"]["tree_size"], new["tree_head"]["tree_size"]
        if a > b:
            raise FortressError("first must not be larger than second")
        tree = _Tree([l for _, l in self._leaves(b)])
        proof = tree.subproof(a, 0, b, True) if 0 < a < b else []
        r1, r2 = bytes.fromhex(old["tree_head"]["root_hash"]), bytes.fromhex(new["tree_head"]["root_hash"])
        return {"first": a, "second": b, "first_root": r1.hex(), "second_root": r2.hex(),
                "proof": [p.hex() for p in proof], "first_tree_head": old, "second_tree_head": new,
                "verified_here": verify_consistency(a, b, r1, r2, proof) if a else True}

    def history(self, limit: int = 50) -> list[dict]:
        rows = self._db.execute("SELECT tree_size, root_hash, timestamp, anchor IS NOT NULL AS anchored FROM tree_heads "
                                "ORDER BY tree_size DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---------------- two-person integrity ----------------

    def tpi_policy(self, org_id: str, name: str, officers: list[str], required: int) -> dict:
        offs = sorted({norm_address(o) for o in officers})
        if len(offs) < 2:
            raise FortressError("two-person integrity needs at least 2 distinct officer wallets")
        if not 2 <= required <= len(offs):
            raise FortressError(f"required approvals must be between 2 and {len(offs)}")
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO tpi_policies VALUES (?,?,?,?,?)",
                             (org_id, name, json.dumps(offs), required, _iso(_now())))
            self._db.commit()
        return {"policy": name, "officers": [checksum(o) for o in offs], "required": required}

    def tpi_request(self, org_id: str, policy: str, stream_id: str, summary: str, details: dict | None,
                    hours: int) -> dict:
        p = self._db.execute("SELECT * FROM tpi_policies WHERE org_id=? AND name=?", (org_id, policy)).fetchone()
        if not p:
            raise FortressError(f"no two-person policy named '{policy}'; create it with fortress_tpi_policy")
        summary = " ".join((summary or "").split())[:300]
        if not summary:
            raise FortressError("summary is required")
        if not 1 <= hours <= 168:
            raise FortressError("hours must be between 1 and 168")
        rid = "tpi_" + secrets.token_hex(8)
        dh = sha256_hex(canonical(details or {}))
        with self._lock:
            self._db.execute("INSERT INTO tpi_requests (request_id, org_id, policy, stream_id, summary, details_hash, "
                             "officers, required, status, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (rid, org_id, policy, stream_id, summary, dh, p["officers"], p["required"], "pending",
                              _iso(_now()), _iso(_now() + timedelta(hours=hours))))
            self._db.commit()
        return self.tpi_public(rid)

    @staticmethod
    def tpi_message(r: dict, decision: str) -> str:
        return (f"Privi Two-Person Integrity {decision.upper()} {r['request_id']}\n"
                f"Action: {r['summary']}\nDetails hash: {r['details_hash']}\nOrganization: {r['org_id']}")

    def tpi_decide(self, rid: str, decision: str, signature: str) -> dict:
        if decision not in ("approve", "veto"):
            raise FortressError("decision must be approve or veto")
        with self._lock:
            r = self._db.execute("SELECT * FROM tpi_requests WHERE request_id=?", (rid,)).fetchone()
            if not r:
                raise FortressError("no such request")
            r = dict(r)
            if self._tpi_status(r) != "pending":
                raise FortressError(f"request is already {self._tpi_status(r)}")
            try:
                who = recover_address(personal_hash(self.tpi_message(r, decision)),
                                      bytes.fromhex(signature.strip().removeprefix("0x")))
            except ValueError as e:
                raise FortressError(f"bad signature: {e}")
            if who not in json.loads(r["officers"]):
                raise FortressError(f"{checksum(who)} is not an officer on this policy")
            approvals = json.loads(r["approvals"])
            if any(a["officer"] == who for a in approvals):
                raise FortressError("this officer already approved; a different officer must approve")
            if decision == "veto":
                self._db.execute("UPDATE tpi_requests SET status='vetoed', vetoed_by=?, decided_at=? WHERE request_id=?",
                                 (who, _iso(_now()), rid))
            else:
                approvals.append({"officer": who, "signature": signature.strip(), "at": _iso(_now())})
                status = "authorized" if len(approvals) >= r["required"] else "pending"
                self._db.execute("UPDATE tpi_requests SET approvals=?, status=?, decided_at=? WHERE request_id=?",
                                 (json.dumps(approvals), status, _iso(_now()) if status == "authorized" else None, rid))
            self._db.commit()
        return self.tpi_public(rid) | {"decided_by": checksum(who), "decision": decision}

    def tpi_execute(self, rid: str, org_id: str) -> dict:
        with self._lock:
            r = self._db.execute("SELECT * FROM tpi_requests WHERE request_id=?", (rid,)).fetchone()
            if not r or r["org_id"] != org_id:
                raise FortressError("no such request for this organization")
            st = self._tpi_status(dict(r))
            if st != "authorized":
                raise FortressError(f"not authorized: request is {st}")
            self._db.execute("UPDATE tpi_requests SET status='executed', executed_at=? WHERE request_id=?",
                             (_iso(_now()), rid))
            self._db.commit()
        return self.tpi_public(rid)

    @staticmethod
    def _tpi_status(r: dict) -> str:
        if r["status"] in ("pending", "authorized") and r["expires_at"] < _iso(_now()):
            return "expired"
        return r["status"]

    def tpi_row(self, rid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM tpi_requests WHERE request_id=?", ((rid or "").strip(),)).fetchone()
        return dict(r) if r else None

    def tpi_public(self, rid: str) -> dict:
        r = self.tpi_row(rid)
        if not r:
            raise FortressError("no such request")
        approvals = json.loads(r["approvals"])
        return {"request_id": r["request_id"], "status": self._tpi_status(r), "org_id": r["org_id"],
                "policy": r["policy"], "stream_id": r["stream_id"], "summary": r["summary"],
                "details_hash": r["details_hash"], "required": r["required"],
                "officers": [checksum(o) for o in json.loads(r["officers"])],
                "approvals": [{"officer": checksum(a["officer"]), "at": a["at"]} for a in approvals],
                "approvals_count": len(approvals), "vetoed_by": checksum(r["vetoed_by"]) if r["vetoed_by"] else None,
                "created_at": r["created_at"], "expires_at": r["expires_at"], "executed_at": r["executed_at"],
                "approve_message": self.tpi_message(r, "approve"), "veto_message": self.tpi_message(r, "veto"),
                "approve_url": f"{self.issuer_url}/tpi/{r['request_id']}"}

    def tpi_list(self, org_id: str) -> list[dict]:
        rows = self._db.execute("SELECT request_id FROM tpi_requests WHERE org_id=? ORDER BY created_at DESC LIMIT 100",
                                (org_id,)).fetchall()
        return [{k: v for k, v in self.tpi_public(r["request_id"]).items() if k not in ("approve_message", "veto_message")}
                for r in rows]

    # ---------------- evidence bundles ----------------

    def bundle(self, org: dict, stream_id: str, checkpoints) -> dict:
        evs = self.ledger.entries(org["org_id"], stream_id)
        if not evs:
            raise FortressError("no entries in that stream")
        if len(evs) > 5000:
            raise FortressError("stream too large for one bundle (5000 entries max)")
        head = evs[-1]["entry_hash"]
        inc = self.inclusion(head)
        cp = checkpoints.latest(f"{org['org_id']}/{stream_id}")
        body = {
            "type": "PriviEvidenceBundle", "version": "1", "issued_at": _iso(_now()), "issuer_url": self.issuer_url,
            "organization": {"org_id": org["org_id"], "name": org["name"]}, "stream_id": stream_id,
            "entries": evs, "chain": {"entry_count": len(evs), "head_hash": head,
                                       "intact": self.ledger.check_chain(evs).valid},
            "inclusion_proof": {k: inc[k] for k in ("entry_hash", "leaf_index", "tree_size", "leaf_hash", "audit_path")},
            "signed_tree_head": inc["signed_tree_head"],
            "onchain_checkpoint": dict(cp) if cp else None,
            "issuer_keys": self.keys(),
            "verify": "python verify_bundle.py bundle.json   (get it at " + self.issuer_url + "/tools/verify_bundle.py)",
        }
        bh = sha256_hex(canonical(body))
        return {"bundle": body, "bundle_hash": bh, "signatures": {"ed25519": self.passports.sign(bh),
                                                                 "ml_dsa_87": self.pq_sign(bh)}}
