"""Privi Supplier Proof: buyers require it, so suppliers join Privi.

A buyer publishes a requirement (e.g. "ISO 9001 certificate, lot traceability,
insurance, AI Act register"). Each supplier answers it from its own Privi
organization with fingerprints (SHA-256) of the evidence documents; Privi never
stores the files. When the buyer approves, Privi issues a certificate naming
both companies and the exact evidence fingerprints, seals its hash on chain, and
publishes a free verification page and badge. Both sides get the event in their
tamper-evident "supplier-proof" log.

The certificate only exists between two Privi organizations: a buyer that
requires Privi Supplier Proof brings every one of its suppliers onto Privi.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sp_requirements (
    req_id      TEXT PRIMARY KEY,
    buyer_org   TEXT NOT NULL,
    title       TEXT NOT NULL,
    items       TEXT NOT NULL,
    valid_days  INTEGER NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sp_submissions (
    sub_id       TEXT PRIMARY KEY,
    req_id       TEXT NOT NULL,
    supplier_org TEXT NOT NULL,
    evidence     TEXT NOT NULL,
    status       TEXT NOT NULL,
    reason       TEXT NOT NULL DEFAULT '',
    cert_id      TEXT,
    created_at   TEXT NOT NULL,
    decided_at   TEXT
);
CREATE TABLE IF NOT EXISTS sp_certs (
    cert_id      TEXT PRIMARY KEY,
    req_id       TEXT NOT NULL,
    buyer_org    TEXT NOT NULL,
    supplier_org TEXT NOT NULL,
    body         TEXT NOT NULL,
    body_hash    TEXT NOT NULL,
    attestation  TEXT NOT NULL,
    issued_at    TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    revoked_at   TEXT,
    revoke_reason TEXT NOT NULL DEFAULT ''
);
"""

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,47}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class SupplierProofError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SupplierProof:
    def __init__(self, ledger, public_url: str):
        self.ledger, self._db, self._lock, self.public_url = ledger, ledger._db, ledger._lock, public_url
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def _org_name(self, org_id: str) -> str:
        r = self._db.execute("SELECT name FROM orgs WHERE org_id=?", (org_id,)).fetchone()
        return r["name"] if r else ""

    # ---- buyer: requirements -------------------------------------------

    def create_requirement(self, buyer_org: str, title: str, items: list[dict], valid_days: int = 365) -> dict:
        title = (title or "").strip()
        if not 3 <= len(title) <= 120:
            raise SupplierProofError("title must be 3-120 characters")
        if not isinstance(items, list) or not 1 <= len(items) <= 30:
            raise SupplierProofError("items must list 1-30 things the supplier has to prove")
        clean, seen = [], set()
        for it in items:
            if not isinstance(it, dict):
                raise SupplierProofError("each item must be like {\"key\": \"iso_9001\", \"label\": \"ISO 9001 certificate\"}")
            k, label = str(it.get("key", "")).strip(), str(it.get("label", "")).strip()
            if not KEY_RE.match(k) or k in seen:
                raise SupplierProofError(f"item key '{k}' must be unique, lowercase letters, digits or _")
            if not 2 <= len(label) <= 200:
                raise SupplierProofError(f"item '{k}' needs a label (2-200 characters)")
            seen.add(k)
            clean.append({"key": k, "label": label, "document_required": bool(it.get("document_required", True))})
        if not isinstance(valid_days, int) or not 1 <= valid_days <= 1095:
            raise SupplierProofError("valid_days must be 1-1095")
        req_id = "req_" + secrets.token_hex(8)
        with self._lock:
            self._db.execute("INSERT INTO sp_requirements VALUES (?,?,?,?,?,1,?)",
                             (req_id, buyer_org, title, json.dumps(clean), valid_days, _iso(_now())))
            self._db.commit()
        self.ledger.record(buyer_org, "supplier-proof", "Privi Ledger", "data_change",
                           f"Published supplier requirement {req_id}: {title}", req_id, "success",
                           {"items": [i["key"] for i in clean], "valid_days": valid_days})
        return {**self.requirement(req_id), "invite_url": f"{self.public_url}/supplier/requirements/{req_id}"}

    def requirement(self, req_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM sp_requirements WHERE req_id=?", (req_id,)).fetchone()
        if not r:
            return None
        return {"req_id": r["req_id"], "title": r["title"], "items": json.loads(r["items"]),
                "valid_days": r["valid_days"], "active": bool(r["active"]), "created_at": r["created_at"],
                "buyer": {"org_id": r["buyer_org"], "name": self._org_name(r["buyer_org"])}}

    def close_requirement(self, buyer_org: str, req_id: str) -> dict:
        req = self.requirement(req_id)
        if not req or req["buyer"]["org_id"] != buyer_org:
            raise SupplierProofError("requirement not found")
        with self._lock:
            self._db.execute("UPDATE sp_requirements SET active=0 WHERE req_id=?", (req_id,))
            self._db.commit()
        return {"req_id": req_id, "active": False}

    # ---- supplier: submit -----------------------------------------------

    def submit(self, supplier_org: str, req_id: str, evidence: dict) -> dict:
        req = self.requirement(req_id)
        if not req or not req["active"]:
            raise SupplierProofError("requirement not found or closed")
        if req["buyer"]["org_id"] == supplier_org:
            raise SupplierProofError("a company cannot certify itself")
        if not isinstance(evidence, dict):
            raise SupplierProofError("evidence must be an object keyed by requirement item")
        keys = {i["key"]: i for i in req["items"]}
        unknown = set(evidence) - set(keys)
        if unknown:
            raise SupplierProofError(f"unknown item(s): {', '.join(sorted(unknown))}")
        clean: dict[str, dict] = {}
        for k, item in keys.items():
            ev = evidence.get(k)
            if not isinstance(ev, dict):
                raise SupplierProofError(f"missing evidence for '{k}' ({item['label']})")
            sha = str(ev.get("sha256", "")).lower().strip()
            if item["document_required"] and not HEX64.match(sha):
                raise SupplierProofError(f"'{k}' needs the SHA-256 (64 hex) of its document")
            if sha and not HEX64.match(sha):
                raise SupplierProofError(f"'{k}': sha256 must be 64 hex characters")
            note, until = str(ev.get("note", ""))[:500], str(ev.get("valid_until", ""))[:10]
            if until:
                try:
                    datetime.fromisoformat(until)
                except ValueError:
                    raise SupplierProofError(f"'{k}': valid_until must be YYYY-MM-DD")
            clean[k] = {k2: v for k2, v in (("sha256", sha), ("note", note), ("valid_until", until)) if v}
        pending = self._db.execute("SELECT sub_id FROM sp_submissions WHERE req_id=? AND supplier_org=? AND status='pending'",
                                   (req_id, supplier_org)).fetchone()
        sub_id = "sub_" + secrets.token_hex(8)
        with self._lock:
            if pending:
                self._db.execute("UPDATE sp_submissions SET status='superseded' WHERE sub_id=?", (pending["sub_id"],))
            self._db.execute("INSERT INTO sp_submissions (sub_id, req_id, supplier_org, evidence, status, created_at) "
                             "VALUES (?,?,?,?, 'pending', ?)", (sub_id, req_id, supplier_org, canon(clean), _iso(_now())))
            self._db.commit()
        supplier_name = self._org_name(supplier_org)
        self.ledger.record(supplier_org, "supplier-proof", "Privi Ledger", "message",
                           f"Submitted proof for {req['buyer']['name']} requirement {req_id}", sub_id, "pending",
                           {"req_id": req_id, "evidence_hash": hashlib.sha256(canon(clean).encode()).hexdigest()})
        self.ledger.record(req["buyer"]["org_id"], "supplier-proof", "Privi Ledger", "message",
                           f"Supplier {supplier_name} submitted proof for {req_id}", sub_id, "pending",
                           {"supplier_org": supplier_org})
        return {"sub_id": sub_id, "status": "pending", "req_id": req_id, "buyer": req["buyer"]}

    def _sub(self, sub_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM sp_submissions WHERE sub_id=?", (sub_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["evidence"] = json.loads(d["evidence"])
        d["supplier"] = {"org_id": d.pop("supplier_org"), "name": self._org_name(r["supplier_org"])}
        return d

    def inbox(self, buyer_org: str, status: str = "pending") -> list[dict]:
        rows = self._db.execute("""SELECT s.sub_id FROM sp_submissions s JOIN sp_requirements q ON q.req_id=s.req_id
                                   WHERE q.buyer_org=? AND s.status=? ORDER BY s.created_at""", (buyer_org, status)).fetchall()
        return [self._sub(r["sub_id"]) for r in rows]

    # ---- buyer: decide -> certificate ------------------------------------

    def decide(self, buyer_org: str, sub_id: str, approve: bool, reason: str = "") -> dict:
        sub = self._sub(sub_id)
        req = self.requirement(sub["req_id"]) if sub else None
        if not sub or not req or req["buyer"]["org_id"] != buyer_org:
            raise SupplierProofError("submission not found")
        if sub["status"] != "pending":
            raise SupplierProofError(f"submission is already {sub['status']}")
        now = _now()
        supplier = sub["supplier"]
        if not approve:
            reason = (reason or "").strip()[:500]
            if not reason:
                raise SupplierProofError("give a reason so the supplier can fix it")
            with self._lock:
                self._db.execute("UPDATE sp_submissions SET status='rejected', reason=?, decided_at=? WHERE sub_id=?",
                                 (reason, _iso(now), sub_id))
                self._db.commit()
            for org in (buyer_org, supplier["org_id"]):
                self.ledger.record(org, "supplier-proof", "Privi Ledger", "approval",
                                   f"Supplier proof {sub_id} rejected: {reason}", sub_id, "failure", {"req_id": req["req_id"]})
            return {"sub_id": sub_id, "status": "rejected", "reason": reason}
        cert_id = "spc_" + secrets.token_hex(8)
        expires = now + timedelta(days=req["valid_days"])
        body = {"type": "privi.supplier_certificate", "version": 1, "cert_id": cert_id,
                "requirement": {"req_id": req["req_id"], "title": req["title"]},
                "buyer": req["buyer"], "supplier": supplier,
                "evidence": {k: {"label": next(i["label"] for i in req["items"] if i["key"] == k), **v}
                             for k, v in sub["evidence"].items()},
                "issued_at": _iso(now), "expires_at": _iso(expires), "issuer": "Privi Ledger",
                "verify_url": f"{self.public_url}/certs/{cert_id}"}
        h = hashlib.sha256(canon(body).encode()).hexdigest()
        return {"cert_id": cert_id, "body": body, "body_hash": h, "sub": sub, "req": req}

    def store_cert(self, buyer_org: str, pending: dict, attestation: dict) -> dict:
        body, cert_id, sub, req = pending["body"], pending["cert_id"], pending["sub"], pending["req"]
        with self._lock:
            cur = self._db.execute("UPDATE sp_submissions SET status='approved', cert_id=?, decided_at=? "
                                   "WHERE sub_id=? AND status='pending'", (cert_id, body["issued_at"], sub["sub_id"]))
            if cur.rowcount != 1:
                self._db.rollback()
                raise SupplierProofError("submission was decided by someone else just now")
            self._db.execute("INSERT INTO sp_certs (cert_id, req_id, buyer_org, supplier_org, body, body_hash, attestation, "
                             "issued_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                             (cert_id, req["req_id"], buyer_org, sub["supplier"]["org_id"], canon(body),
                              pending["body_hash"], json.dumps(attestation), body["issued_at"], body["expires_at"]))
            self._db.commit()
        for org, who in ((buyer_org, f"supplier {sub['supplier']['name']}"), (sub["supplier"]["org_id"], req["buyer"]["name"])):
            self.ledger.record(org, "supplier-proof", "Privi Ledger", "approval",
                               f"Supplier certificate {cert_id} issued ({who}: {req['title']})", cert_id, "success",
                               {"body_hash": pending["body_hash"], "anchored": attestation.get("anchored")})
        return self.get(cert_id)

    def get(self, cert_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM sp_certs WHERE cert_id=?", (cert_id,)).fetchone()
        if not r:
            return None
        return {"cert_id": r["cert_id"], "certificate": json.loads(r["body"]), "body_hash": r["body_hash"],
                "attestation": json.loads(r["attestation"]), "revoked_at": r["revoked_at"],
                "revoke_reason": r["revoke_reason"], "expires_at": r["expires_at"]}

    def verify(self, cert_id: str, document_sha256: str | None = None) -> dict:
        rec = self.get(cert_id)
        if not rec:
            return {"valid": False, "cert_id": cert_id, "reason": "no such certificate"}
        recomputed = hashlib.sha256(canon(rec["certificate"]).encode()).hexdigest()
        expired = rec["expires_at"] < _iso(_now())
        out = {"cert_id": cert_id, "valid": recomputed == rec["body_hash"] and not rec["revoked_at"] and not expired,
               "untampered": recomputed == rec["body_hash"], "revoked": bool(rec["revoked_at"]), "expired": expired,
               "certificate": rec["certificate"], "body_hash": rec["body_hash"], "attestation": rec["attestation"]}
        if rec["revoked_at"]:
            out["revoke_reason"] = rec["revoke_reason"]
        if document_sha256:
            d = document_sha256.lower().strip()
            out["document_matches"] = [k for k, v in rec["certificate"]["evidence"].items() if v.get("sha256") == d]
        return out

    def revoke(self, buyer_org: str, cert_id: str, reason: str) -> dict:
        rec = self._db.execute("SELECT buyer_org, supplier_org, revoked_at FROM sp_certs WHERE cert_id=?", (cert_id,)).fetchone()
        if not rec or rec["buyer_org"] != buyer_org:
            raise SupplierProofError("certificate not found")
        if rec["revoked_at"]:
            raise SupplierProofError("already revoked")
        reason = (reason or "").strip()[:500] or "revoked by buyer"
        with self._lock:
            self._db.execute("UPDATE sp_certs SET revoked_at=?, revoke_reason=? WHERE cert_id=?", (_iso(_now()), reason, cert_id))
            self._db.commit()
        for org in (buyer_org, rec["supplier_org"]):
            self.ledger.record(org, "supplier-proof", "Privi Ledger", "data_change",
                               f"Supplier certificate {cert_id} revoked: {reason}", cert_id, "success", {})
        return {"cert_id": cert_id, "revoked": True, "reason": reason}

    def list_certs(self, org_id: str) -> list[dict]:
        rows = self._db.execute("SELECT cert_id, buyer_org, supplier_org, expires_at, revoked_at FROM sp_certs "
                                "WHERE buyer_org=? OR supplier_org=? ORDER BY issued_at DESC", (org_id, org_id)).fetchall()
        return [{"cert_id": r["cert_id"], "as": "buyer" if r["buyer_org"] == org_id else "supplier",
                 "counterparty": self._org_name(r["supplier_org"] if r["buyer_org"] == org_id else r["buyer_org"]),
                 "expires_at": r["expires_at"], "revoked": bool(r["revoked_at"]),
                 "verify_url": f"{self.public_url}/certs/{r['cert_id']}"} for r in rows]


def badge_svg(label: str, ok: bool) -> str:
    color = "#1f9d55" if ok else "#c0392b"
    text = "verified" if ok else label
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="190" height="20" role="img" aria-label="Privi {text}">'
            f'<rect width="96" height="20" fill="#333"/><rect x="96" width="94" height="20" fill="{color}"/>'
            f'<g fill="#fff" font-family="Verdana,sans-serif" font-size="11">'
            f'<text x="8" y="14">Privi supplier</text><text x="104" y="14">{text}</text></g></svg>')
