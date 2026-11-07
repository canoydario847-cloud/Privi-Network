# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi RealCheck: "is it really you?" for every phone and computer user at a company.

Voice clones, deepfake video calls, spoofed caller ID and look-alike email addresses make "the CEO is on the
phone, wire the money now" easy to fake. RealCheck moves the proof off the channel the attacker controls:

1. A company enrolls its people. Each person registers a passkey (Face ID / fingerprint / screen lock) on
   their own phone or laptop. Privi stores only the passkey's public key.
2. When someone asks for money, data, a password reset or anything unusual, the company creates a check for
   the person they claim to be. The approve link goes to that person's enrolled device, not to the caller.
3. Only that person's passkey, with the person verified on the device, can confirm it. They can also press
   "That's not me", which flags the request as impersonation.
4. The result is a Privi-signed receipt (Ed25519 + ML-DSA) the company keeps as evidence. Checks expire in
   10 minutes.

What it does not prove: that the person meant to approve the underlying payment, or that their unlocked phone
wasn't in someone else's hands. It proves their enrolled passkey answered, with the device's user verification.

Paid only: an organization is activated by Privi after payment (REALCHECK plan, USDC on Base) and stops
creating checks when its paid period ends.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .humans import HumanError, HumanRegistry, b64u, unb64u

CHECK_TTL_S = 600
ENROLL_TTL_S = 7 * 86400
PRICE = {"plan": "Privi RealCheck", "usd_per_month": 49, "seats": 25, "pay": "https://privi-hub.onrender.com/pay/#realcheck"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS real_orgs (
    org_id      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    key_hash    TEXT NOT NULL UNIQUE,
    seats       INTEGER NOT NULL,
    paid_until  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS real_members (
    member_id    TEXT PRIMARY KEY,
    org_id       TEXT NOT NULL,
    name         TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT '',
    enroll_hash  TEXT,
    enroll_until REAL,
    enroll_nonce TEXT,
    human_id     TEXT,
    enrolled_at  TEXT,
    removed      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS real_checks (
    check_id     TEXT PRIMARY KEY,
    org_id       TEXT NOT NULL,
    member_id    TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    reason       TEXT NOT NULL,
    channel      TEXT NOT NULL,
    nonce        TEXT NOT NULL,
    status       TEXT NOT NULL,          -- pending | confirmed | denied | expired
    created_at   TEXT NOT NULL,
    expires_at   REAL NOT NULL,
    decided_at   TEXT,
    receipt_id   TEXT
);
"""

CHANNELS = ("phone call", "text message", "email", "video call", "chat", "in person", "other")


class RealCheckError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _iso(d: datetime | None = None) -> str:
    return (d or datetime.now(timezone.utc)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RealCheck:
    def __init__(self, db_path: str, humans: HumanRegistry, attestor, public_url: str):
        self.humans, self.attestor, self.public_url = humans, attestor, public_url.rstrip("/")
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # ---- organizations (activated by Privi after payment) ----------------------------------

    def create_org(self, name: str, seats: int = 25, paid_days: int = 30) -> dict:
        name = (name or "").strip()[:120]
        if not name:
            raise RealCheckError("organization name is required")
        if not 1 <= int(seats) <= 10000 or not 1 <= int(paid_days) <= 3660:
            raise RealCheckError("seats must be 1-10000 and paid_days 1-3660")
        org_id, key = "rorg_" + secrets.token_hex(6), "rck_" + secrets.token_urlsafe(24)
        until = _iso(datetime.now(timezone.utc) + timedelta(days=int(paid_days)))
        with self._lock:
            self._db.execute("INSERT INTO real_orgs VALUES (?,?,?,?,?,?)", (org_id, name, _h(key), int(seats), until, _iso()))
            self._db.commit()
        return {"org_id": org_id, "name": name, "org_key": key, "seats": int(seats), "paid_until": until,
                "note": "Store org_key now; it is shown once. Send it as 'Authorization: Bearer <org_key>'."}

    def extend(self, org_id: str, days: int) -> dict:
        org = self._org_by_id(org_id)
        base = max(datetime.now(timezone.utc), datetime.fromisoformat(org["paid_until"].replace("Z", "+00:00")))
        until = _iso(base + timedelta(days=int(days)))
        with self._lock:
            self._db.execute("UPDATE real_orgs SET paid_until=? WHERE org_id=?", (until, org_id))
            self._db.commit()
        return {"org_id": org_id, "paid_until": until}

    def _org_by_id(self, org_id: str) -> dict:
        r = self._db.execute("SELECT * FROM real_orgs WHERE org_id=?", (org_id,)).fetchone()
        if not r:
            raise RealCheckError("unknown organization", 404)
        return dict(r)

    def org_from_key(self, key: str) -> dict:
        r = self._db.execute("SELECT * FROM real_orgs WHERE key_hash=?", (_h(key or ""),)).fetchone() if key else None
        if not r:
            raise RealCheckError("missing or invalid organization key", 401)
        return dict(r)

    @staticmethod
    def _require_paid(org: dict) -> None:
        if org["paid_until"] < _iso():
            raise RealCheckError(f"the {PRICE['plan']} plan for this organization has ended; renew at {PRICE['pay']}", 402)

    # ---- people --------------------------------------------------------------------------------

    def add_member(self, org: dict, name: str, role: str = "") -> dict:
        self._require_paid(org)
        name = (name or "").strip()[:80]
        if not name:
            raise RealCheckError("member name is required")
        used = self._db.execute("SELECT COUNT(*) FROM real_members WHERE org_id=? AND removed=0", (org["org_id"],)).fetchone()[0]
        if used >= org["seats"]:
            raise RealCheckError(f"all {org['seats']} seats are used; add seats at {PRICE['pay']}", 402)
        mid, token = "rmem_" + secrets.token_hex(6), "renr_" + secrets.token_urlsafe(24)
        with self._lock:
            self._db.execute("INSERT INTO real_members (member_id, org_id, name, role, enroll_hash, enroll_until, enroll_nonce)"
                             " VALUES (?,?,?,?,?,?,?)", (mid, org["org_id"], name, (role or "").strip()[:80], _h(token),
                                                          time.time() + ENROLL_TTL_S, b64u(secrets.token_bytes(32))))
            self._db.commit()
        return {"member_id": mid, "name": name, "enroll_url": f"{self.public_url}/real/enroll/{token}",
                "enroll_expires_in_days": ENROLL_TTL_S // 86400,
                "note": "Send the enroll link to this person yourself (in person or a channel you already trust). "
                        "They open it on their own phone and register a passkey."}

    def members(self, org: dict) -> list[dict]:
        rows = self._db.execute("SELECT member_id, name, role, enrolled_at FROM real_members WHERE org_id=? AND removed=0"
                                " ORDER BY name", (org["org_id"],)).fetchall()
        return [{**dict(r), "enrolled": bool(r["enrolled_at"])} for r in rows]

    def remove_member(self, org: dict, member_id: str) -> dict:
        with self._lock:
            n = self._db.execute("UPDATE real_members SET removed=1 WHERE member_id=? AND org_id=?",
                                 (member_id, org["org_id"])).rowcount
            self._db.commit()
        if not n:
            raise RealCheckError("unknown member", 404)
        return {"member_id": member_id, "removed": True}

    def _enrollment(self, token: str) -> dict:
        r = self._db.execute("SELECT m.*, o.name AS org_name FROM real_members m JOIN real_orgs o USING(org_id) "
                             "WHERE m.enroll_hash=? AND m.removed=0", (_h(token or ""),)).fetchone()
        if not r or (r["enroll_until"] or 0) < time.time():
            raise RealCheckError("this enroll link is unknown, used or expired; ask your administrator for a new one", 404)
        return dict(r)

    def enroll_challenge(self, token: str) -> bytes:
        m = self._enrollment(token)
        return hashlib.sha256(unb64u(m["enroll_nonce"]) + f"|realcheck-enroll|{m['member_id']}".encode()).digest()

    def enroll_options(self, token: str) -> dict:
        m = self._enrollment(token)
        ch = b64u(self.enroll_challenge(token))
        return {"member": m["name"], "organization": m["org_name"],
                "create": {"challenge": ch, "rp": {"id": self.humans.rp_id, "name": "Privi RealCheck"},
                           "user": {"id": b64u(m["member_id"].encode()), "name": m["name"],
                                    "displayName": f"{m['name']} ({m['org_name']})"},
                           "pubKeyCredParams": [{"type": "public-key", "alg": -8}, {"type": "public-key", "alg": -7},
                                                {"type": "public-key", "alg": -257}],
                           "authenticatorSelection": {"residentKey": "preferred", "userVerification": "required"},
                           "attestation": "none", "timeout": 120000}}

    def enroll_finish(self, token: str, cred: dict) -> dict:
        m = self._enrollment(token)
        try:
            human_id, _ = self.humans.register_passkey(cred, self.enroll_challenge(token))
        except HumanError as e:
            raise RealCheckError(str(e))
        with self._lock:
            self._db.execute("UPDATE real_members SET human_id=?, enrolled_at=?, enroll_hash=NULL, enroll_until=NULL "
                             "WHERE member_id=?", (human_id, _iso(), m["member_id"]))
            self._db.commit()
        return {"enrolled": True, "member": m["name"], "organization": m["org_name"]}

    # ---- checks ----------------------------------------------------------------------------------

    def create_check(self, org: dict, member_id: str, requested_by: str, reason: str, channel: str = "other") -> dict:
        self._require_paid(org)
        m = self._db.execute("SELECT * FROM real_members WHERE member_id=? AND org_id=? AND removed=0",
                             (member_id, org["org_id"])).fetchone()
        if not m:
            raise RealCheckError("unknown member", 404)
        if not m["human_id"]:
            raise RealCheckError(f"{m['name']} has not enrolled a passkey yet; send them their enroll link first", 409)
        channel = channel if channel in CHANNELS else "other"
        cid = "rchk_" + secrets.token_hex(8)
        with self._lock:
            self._db.execute("INSERT INTO real_checks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             (cid, org["org_id"], member_id, (requested_by or "").strip()[:80] or "a colleague",
                              (reason or "").strip()[:240] or "confirm it is really you", channel,
                              b64u(secrets.token_bytes(32)), "pending", _iso(), time.time() + CHECK_TTL_S, None, None))
            self._db.commit()
        return {"check_id": cid, "member": m["name"], "status": "pending",
                "approve_url": f"{self.public_url}/real/c/{cid}",
                "expires_in_minutes": CHECK_TTL_S // 60,
                "how": f"Send approve_url to {m['name']} through a channel you already trust (their saved number, "
                       "work chat, or in person), never through the call, text or email being checked. "
                       f"Then poll GET /real/v1/checks/{cid}. Until it says 'confirmed', treat the request as fake."}

    def _check_row(self, cid: str) -> dict:
        r = self._db.execute("SELECT c.*, m.name AS member_name, m.human_id, o.name AS org_name FROM real_checks c "
                             "JOIN real_members m USING(member_id) JOIN real_orgs o ON o.org_id=c.org_id "
                             "WHERE c.check_id=?", (cid,)).fetchone()
        if not r:
            raise RealCheckError("unknown check", 404)
        r = dict(r)
        if r["status"] == "pending" and r["expires_at"] < time.time():
            with self._lock:
                self._db.execute("UPDATE real_checks SET status='expired' WHERE check_id=? AND status='pending'", (cid,))
                self._db.commit()
            r["status"] = "expired"
        return r

    def check_challenge(self, cid: str, decision: str) -> bytes:
        r = self._check_row(cid)
        return hashlib.sha256(unb64u(r["nonce"]) + f"|realcheck|{cid}|{r['member_id']}|{decision}".encode()).digest()

    def public_check(self, cid: str) -> dict:
        """What the person being checked sees on their approve page (no secrets)."""
        r = self._check_row(cid)
        return {"check_id": cid, "organization": r["org_name"], "member": r["member_name"],
                "requested_by": r["requested_by"], "reason": r["reason"], "channel": r["channel"],
                "status": r["status"], "expires_at": _iso(datetime.fromtimestamp(r["expires_at"], timezone.utc))}

    def decide_options(self, cid: str, decision: str) -> dict:
        if decision not in ("confirm", "deny"):
            raise RealCheckError("decision must be confirm or deny")
        r = self._check_row(cid)
        if r["status"] != "pending":
            raise RealCheckError(f"this check is already {r['status']}", 409)
        return {"get": self.humans.get_options(self.check_challenge(cid, decision))}

    def decide(self, cid: str, decision: str, cred: dict) -> dict:
        if decision not in ("confirm", "deny"):
            raise RealCheckError("decision must be confirm or deny")
        r = self._check_row(cid)
        if r["status"] != "pending":
            raise RealCheckError(f"this check is already {r['status']}", 409)
        try:
            human_id, cred_id = self.humans.verify_assertion(cred, self.check_challenge(cid, decision))
        except HumanError as e:
            raise RealCheckError(str(e))
        if not hmac.compare_digest(human_id, r["human_id"] or ""):
            raise RealCheckError("this passkey does not belong to the person being checked", 403)
        status = "confirmed" if decision == "confirm" else "denied"
        body = {"type": "privi.realcheck/v1", "check_id": cid, "organization": r["org_name"], "org_id": r["org_id"],
                "member": r["member_name"], "member_id": r["member_id"], "requested_by": r["requested_by"],
                "reason": r["reason"], "channel": r["channel"], "result": status,
                "method": "member's enrolled passkey, user verified on device", "credential_id_sha256":
                hashlib.sha256(cred_id.encode()).hexdigest(), "requested_at": r["created_at"], "decided_at": _iso()}
        att = self.attestor.issue("realcheck", body)
        with self._lock:
            self._db.execute("UPDATE real_checks SET status=?, decided_at=?, receipt_id=? WHERE check_id=? AND status='pending'",
                             (status, body["decided_at"], att.get("attestation_id") or att.get("id"), cid))
            self._db.commit()
        return {"check_id": cid, "result": status, "receipt": att}

    def status(self, org: dict, cid: str) -> dict:
        r = self._check_row(cid)
        if r["org_id"] != org["org_id"]:
            raise RealCheckError("unknown check", 404)
        out = {**self.public_check(cid), "decided_at": r["decided_at"]}
        out["verdict"] = {"confirmed": "It really is them. Their enrolled passkey confirmed it.",
                          "denied": "IMPERSONATION: the real person says this request is not from them. Do not act on it.",
                          "expired": "Not confirmed in time. Treat the request as fake.",
                          "pending": "Waiting for the real person. Treat the request as fake until confirmed."}[r["status"]]
        if r["receipt_id"]:
            out["receipt"] = self.attestor.get(r["receipt_id"])
            out["receipt_url"] = f"{self.public_url}/receipts/{r['receipt_id']}"
        return out
