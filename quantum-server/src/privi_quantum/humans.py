# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Human trust factors for quantum agents: biometric human approval and human ID verification.

Biometric approval uses passkeys (WebAuthn / FIDO2) with user verification required: the person
approves an agent with Face ID, Touch ID, Windows Hello or the device's screen-lock check. The biometric
check happens on the person's own device and never reaches Privi. Privi receives only a public-key
signature over a challenge bound to that agent and its post-quantum key, with the authenticator's
"user verified" flag set. Privi stores the passkey's public key, never a fingerprint or face.

ID verification uses Stripe Identity (government ID document plus a matching live selfie). Stripe holds
the documents and selfie; Privi stores only that the check passed, the provider's session id and the date.
A Privi administrator can also record an in-person check ("manual"), which counts for less in the grade.

What this does not prove: a passkey's user-verification flag is reported by the person's device (it can be a
device PIN as well as a biometric), and Privi does not verify authenticator attestation. It proves a real,
present person with a screen-locked device approved the agent; ID verification ties that person to an ID.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import struct
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx2
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

APPROVAL_DAYS = 180
REQUEST_TTL_S = 1800
HUMAN_SESSION_TTL_S = 900
STRIPE_TOLERANCE_S = 300

SCHEMA = """
CREATE TABLE IF NOT EXISTS humans (
    human_id      TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    id_status     TEXT NOT NULL DEFAULT 'none',      -- none | pending | verified | failed
    id_method     TEXT NOT NULL DEFAULT '',          -- stripe_identity | manual
    id_ref        TEXT NOT NULL DEFAULT '',          -- provider session id (no documents)
    id_verified_at TEXT
);
CREATE TABLE IF NOT EXISTS human_passkeys (
    credential_id TEXT PRIMARY KEY,                  -- base64url
    human_id      TEXT NOT NULL,
    cose_key      TEXT NOT NULL,                     -- base64 of the COSE public key
    sign_count    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_requests (
    request_id  TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    challenge   TEXT NOT NULL,                       -- base64url
    expires_at  REAL NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS human_approvals (
    agent_id      TEXT PRIMARY KEY,
    human_id      TEXT NOT NULL,
    credential_id TEXT NOT NULL,
    user_verified INTEGER NOT NULL,
    approved_at   TEXT NOT NULL,
    key_fingerprint TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS human_sessions (
    token_hash TEXT PRIMARY KEY,
    human_id   TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


class HumanError(ValueError):
    pass


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    s = s or ""
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime | None = None) -> str:
    return (d or _now()).isoformat(timespec="seconds")


# ---------------------------------------------------------------- minimal CBOR (decode)

def cbor_decode(data: bytes) -> Any:
    val, pos = _cbor(data, 0)
    return val


def cbor_decode_prefix(data: bytes, pos: int) -> tuple[Any, int]:
    return _cbor(data, pos)


def _cbor(d: bytes, p: int) -> tuple[Any, int]:
    if p >= len(d):
        raise HumanError("truncated CBOR")
    ib = d[p]
    p += 1
    major, info = ib >> 5, ib & 31
    if info < 24:
        n = info
    elif info == 24:
        n = d[p]; p += 1
    elif info == 25:
        n = struct.unpack(">H", d[p:p + 2])[0]; p += 2
    elif info == 26:
        n = struct.unpack(">I", d[p:p + 4])[0]; p += 4
    elif info == 27:
        n = struct.unpack(">Q", d[p:p + 8])[0]; p += 8
    else:
        raise HumanError("unsupported CBOR encoding")
    if major == 0:
        return n, p
    if major == 1:
        return -1 - n, p
    if major in (2, 3):
        chunk = d[p:p + n]
        if len(chunk) != n:
            raise HumanError("truncated CBOR")
        return (chunk if major == 2 else chunk.decode("utf-8")), p + n
    if major == 4:
        out = []
        for _ in range(n):
            v, p = _cbor(d, p)
            out.append(v)
        return out, p
    if major == 5:
        m = {}
        for _ in range(n):
            k, p = _cbor(d, p)
            v, p = _cbor(d, p)
            m[k] = v
        return m, p
    if major == 7:
        return {20: False, 21: True, 22: None}.get(info, None), p
    raise HumanError("unsupported CBOR type")


# ---------------------------------------------------------------- WebAuthn

def cose_verify(cose: dict, signature: bytes, data: bytes) -> bool:
    kty, alg = cose.get(1), cose.get(3)
    try:
        if kty == 2 and alg == -7 and cose.get(-1) == 1:
            x, y = int.from_bytes(cose[-2], "big"), int.from_bytes(cose[-3], "big")
            ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key().verify(signature, data, ec.ECDSA(hashes.SHA256()))
        elif kty == 3 and alg == -257:
            n, e = int.from_bytes(cose[-1], "big"), int.from_bytes(cose[-2], "big")
            rsa.RSAPublicNumbers(e, n).public_key().verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
        elif kty == 1 and alg == -8 and cose.get(-1) == 6:
            Ed25519PublicKey.from_public_bytes(cose[-2]).verify(signature, data)
        else:
            return False
        return True
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return False


def parse_auth_data(ad: bytes) -> dict:
    if len(ad) < 37:
        raise HumanError("authenticator data too short")
    flags = ad[32]
    out = {"rp_id_hash": ad[:32], "up": bool(flags & 0x01), "uv": bool(flags & 0x04),
           "sign_count": struct.unpack(">I", ad[33:37])[0]}
    if flags & 0x40:
        if len(ad) < 55:
            raise HumanError("attested credential data missing")
        cred_len = struct.unpack(">H", ad[53:55])[0]
        cred_id = ad[55:55 + cred_len]
        cose, _ = cbor_decode_prefix(ad, 55 + cred_len)
        out.update(credential_id=cred_id, cose=cose, cose_raw=ad[55 + cred_len:])
    return out


class HumanRegistry:
    def __init__(self, db_path: str, public_url: str, rp_id: str = "", stripe_key: str = "",
                 stripe_webhook_secret: str = "", http: httpx2.Client | None = None):
        self.public_url = public_url.rstrip("/")
        self.origin = self.public_url
        self.rp_id = rp_id or (urlsplit(self.public_url).hostname or "localhost")
        self.stripe_key, self.stripe_webhook_secret = stripe_key, stripe_webhook_secret
        self._http = http
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    @property
    def http(self) -> httpx2.Client:
        if self._http is None:
            self._http = httpx2.Client(base_url="https://api.stripe.com", timeout=20.0)
        return self._http

    # ---- approval requests --------------------------------------------------

    def new_request(self, agent_id: str) -> dict:
        rid = "hreq_" + secrets.token_hex(8)
        with self._lock:
            self._db.execute("DELETE FROM human_requests WHERE expires_at < ?", (time.time(),))
            self._db.execute("INSERT INTO human_requests VALUES (?,?,?,?,0)",
                             (rid, agent_id, b64u(secrets.token_bytes(32)), time.time() + REQUEST_TTL_S))
            self._db.commit()
        return {"request_id": rid, "approval_url": f"{self.public_url}/humans/approve/{rid}",
                "expires_in_minutes": REQUEST_TTL_S // 60}

    def request(self, rid: str) -> dict:
        r = self._db.execute("SELECT * FROM human_requests WHERE request_id=?", (rid,)).fetchone()
        if not r or r["done"] or r["expires_at"] < time.time():
            raise HumanError("this approval link is unknown, used or expired; ask the agent for a new one")
        return dict(r)

    def bound_challenge(self, rid: str, key_fingerprint: str) -> bytes:
        """The WebAuthn challenge: the request's random nonce bound to this agent and its post-quantum key."""
        r = self.request(rid)
        return hashlib.sha256(unb64u(r["challenge"]) + f"|{r['agent_id']}|{key_fingerprint}".encode()).digest()

    def options(self, rid: str, key_fingerprint: str, agent_name: str) -> dict:
        ch = b64u(self.bound_challenge(rid, key_fingerprint))
        return {
            "create": {"challenge": ch, "rp": {"id": self.rp_id, "name": "Privi"},
                       "user": {"id": b64u(secrets.token_bytes(16)), "name": "Privi human",
                                "displayName": "Privi human approver"},
                       "pubKeyCredParams": [{"type": "public-key", "alg": -8}, {"type": "public-key", "alg": -7},
                                            {"type": "public-key", "alg": -257}],
                       "authenticatorSelection": {"residentKey": "required", "userVerification": "required"},
                       "attestation": "none", "timeout": 120000},
            "get": {"challenge": ch, "rpId": self.rp_id, "userVerification": "required", "timeout": 120000},
            "agent_name": agent_name,
        }

    def _check_client(self, client_data_b64: str, typ: str, challenge: bytes) -> bytes:
        raw = unb64u(client_data_b64)
        try:
            cd = json.loads(raw)
        except ValueError:
            raise HumanError("bad clientDataJSON")
        if cd.get("type") != typ:
            raise HumanError("wrong WebAuthn ceremony type")
        if not hmac.compare_digest(unb64u(cd.get("challenge", "")), challenge):
            raise HumanError("challenge mismatch")
        if cd.get("origin") != self.origin:
            raise HumanError("wrong origin")
        return raw

    def finish(self, rid: str, agent_id: str, key_fingerprint: str, cred: dict) -> dict:
        """Verify a passkey registration (create) or sign-in (get) for this approval and bind the agent."""
        req = self.request(rid)
        if req["agent_id"] != agent_id:
            raise HumanError("request does not belong to this agent")
        challenge = self.bound_challenge(rid, key_fingerprint)
        resp = cred.get("response") or {}
        rp_hash = hashlib.sha256(self.rp_id.encode()).digest()
        if resp.get("attestationObject"):
            self._check_client(resp.get("clientDataJSON", ""), "webauthn.create", challenge)
            att = cbor_decode(unb64u(resp["attestationObject"]))
            ad = parse_auth_data(att.get("authData", b""))
            if ad["rp_id_hash"] != rp_hash:
                raise HumanError("passkey is for a different site")
            if not (ad["up"] and ad["uv"]):
                raise HumanError("the device did not verify the person (biometric or screen lock); try again")
            if "cose" not in ad or not isinstance(ad["cose"], dict) or ad["cose"].get(3) not in (-7, -8, -257):
                raise HumanError("unsupported passkey type")
            cid = b64u(ad["credential_id"])
            human_id = "human_" + secrets.token_hex(8)
            with self._lock:
                if self._db.execute("SELECT 1 FROM human_passkeys WHERE credential_id=?", (cid,)).fetchone():
                    raise HumanError("this passkey is already registered; use 'Approve with my passkey'")
                self._db.execute("INSERT INTO humans (human_id, created_at) VALUES (?,?)", (human_id, _iso()))
                self._db.execute("INSERT INTO human_passkeys VALUES (?,?,?,?,?)",
                                 (cid, human_id, base64.b64encode(_cose_bytes(ad)).decode(), ad["sign_count"], _iso()))
                self._db.commit()
            created = True
        else:
            human_id, cid = self.verify_assertion(cred, challenge)
            created = False
        with self._lock:
            self._db.execute("UPDATE human_requests SET done=1 WHERE request_id=?", (rid,))
            self._db.execute("INSERT OR REPLACE INTO human_approvals VALUES (?,?,?,?,?,?)",
                             (agent_id, human_id, cid, 1, _iso(), key_fingerprint))
            token = "hsess_" + secrets.token_urlsafe(24)
            self._db.execute("INSERT INTO human_sessions VALUES (?,?,?)",
                             (hashlib.sha256(token.encode()).hexdigest(), human_id, time.time() + HUMAN_SESSION_TTL_S))
            self._db.commit()
        return {"approved": True, "agent_id": agent_id, "human_id": human_id, "new_passkey": created,
                "human_session": token, "id_verified": self.human(human_id)["id_status"] == "verified"}

    def verify_assertion(self, cred: dict, challenge: bytes) -> tuple[str, str]:
        """Verify a passkey sign-in (navigator.credentials.get) over `challenge` with the person verified.
        Returns (human_id, credential_id). Used for agent approval and for signing quantum mandates."""
        resp = cred.get("response") or {}
        rp_hash = hashlib.sha256(self.rp_id.encode()).digest()
        raw_cd = self._check_client(resp.get("clientDataJSON", ""), "webauthn.get", challenge)
        cid = cred.get("id") or cred.get("rawId") or ""
        row = self._db.execute("SELECT * FROM human_passkeys WHERE credential_id=?", (cid,)).fetchone()
        if not row:
            raise HumanError("unknown passkey; create one on this page first")
        ad_raw = unb64u(resp.get("authenticatorData", ""))
        ad = parse_auth_data(ad_raw)
        if ad["rp_id_hash"] != rp_hash:
            raise HumanError("passkey is for a different site")
        if not (ad["up"] and ad["uv"]):
            raise HumanError("the device did not verify the person (biometric or screen lock); try again")
        cose = cbor_decode(base64.b64decode(row["cose_key"]))
        if not cose_verify(cose, unb64u(resp.get("signature", "")), ad_raw + hashlib.sha256(raw_cd).digest()):
            raise HumanError("passkey signature does not verify")
        if ad["sign_count"] and row["sign_count"] and ad["sign_count"] <= row["sign_count"]:
            raise HumanError("passkey counter went backwards; this passkey may be cloned")
        with self._lock:
            self._db.execute("UPDATE human_passkeys SET sign_count=? WHERE credential_id=?", (ad["sign_count"], cid))
            self._db.commit()
        return row["human_id"], cid

    def get_options(self, challenge: bytes) -> dict:
        return {"challenge": b64u(challenge), "rpId": self.rp_id, "userVerification": "required", "timeout": 120000}

    # ---- lookups ------------------------------------------------------------------

    def human(self, human_id: str) -> dict:
        r = self._db.execute("SELECT * FROM humans WHERE human_id=?", (human_id,)).fetchone()
        if not r:
            raise HumanError("unknown human")
        return dict(r)

    def approval(self, agent_id: str, key_fingerprint: str | None = None) -> dict | None:
        r = self._db.execute("SELECT * FROM human_approvals WHERE agent_id=?", (agent_id,)).fetchone()
        if not r:
            return None
        a = dict(r)
        h = self.human(a["human_id"])
        expires = datetime.fromisoformat(a["approved_at"]) + timedelta(days=APPROVAL_DAYS)
        a.update(expires_at=_iso(expires), current=expires > _now() and
                 (key_fingerprint is None or key_fingerprint == a["key_fingerprint"]),
                 id_status=h["id_status"], id_method=h["id_method"], id_verified_at=h["id_verified_at"])
        return a

    def public_factors(self, agent_id: str, key_fingerprint: str | None = None) -> dict:
        a = self.approval(agent_id, key_fingerprint)
        if not a:
            return {"human_approved": False, "id_verified": False}
        return {"human_approved": bool(a["current"]), "human_approved_at": a["approved_at"],
                "human_approval_expires": a["expires_at"], "approval_method": "passkey, user verified",
                "human_id": a["human_id"], "id_verified": a["id_status"] == "verified",
                "id_method": a["id_method"] or None, "id_verified_at": a["id_verified_at"]}

    def session_human(self, token: str) -> str:
        r = self._db.execute("SELECT * FROM human_sessions WHERE token_hash=?",
                             (hashlib.sha256((token or "").encode()).hexdigest(),)).fetchone()
        if not r or r["expires_at"] < time.time():
            raise HumanError("your approval session expired; approve the agent again to verify your ID")
        return r["human_id"]

    # ---- ID verification (Stripe Identity) -------------------------------------------

    @property
    def stripe_ready(self) -> bool:
        return bool(self.stripe_key)

    def start_id(self, human_session: str) -> dict:
        human_id = self.session_human(human_session)
        if not self.stripe_ready:
            raise HumanError("ID verification is not switched on yet (Privi has not connected Stripe Identity)")
        h = self.human(human_id)
        if h["id_status"] == "verified":
            return {"human_id": human_id, "id_status": "verified"}
        r = self.http.post("/v1/identity/verification_sessions", auth=(self.stripe_key, ""), data={
            "type": "document", "options[document][require_matching_selfie]": "true",
            "options[document][require_live_capture]": "true", "client_reference_id": human_id,
            "metadata[human_id]": human_id, "return_url": f"{self.public_url}/humans/id/return?human={human_id}"})
        if r.status_code >= 400:
            raise HumanError("ID verification could not start; try again later")
        s = r.json()
        with self._lock:
            self._db.execute("UPDATE humans SET id_status='pending', id_method='stripe_identity', id_ref=? WHERE human_id=?",
                             (s["id"], human_id))
            self._db.commit()
        return {"human_id": human_id, "id_status": "pending", "verify_url": s["url"]}

    def _mark(self, human_id: str, status: str, method: str, ref: str) -> None:
        with self._lock:
            self._db.execute("UPDATE humans SET id_status=?, id_method=?, id_ref=?, id_verified_at=? WHERE human_id=?",
                             (status, method, ref, _iso() if status == "verified" else None, human_id))
            self._db.commit()

    def refresh_id(self, human_id: str) -> dict:
        """Ask Stripe for the session's status (used when the person returns from Stripe)."""
        h = self.human(human_id)
        if h["id_method"] != "stripe_identity" or not h["id_ref"] or not self.stripe_ready:
            return {"human_id": human_id, "id_status": h["id_status"]}
        r = self.http.get(f"/v1/identity/verification_sessions/{h['id_ref']}", auth=(self.stripe_key, ""))
        if r.status_code < 400:
            st = r.json().get("status")
            if st == "verified":
                self._mark(human_id, "verified", "stripe_identity", h["id_ref"])
            elif st in ("canceled",):
                self._mark(human_id, "failed", "stripe_identity", h["id_ref"])
        return {"human_id": human_id, "id_status": self.human(human_id)["id_status"]}

    def stripe_webhook(self, payload: bytes, sig_header: str) -> dict:
        if not self.stripe_webhook_secret:
            raise HumanError("webhook secret not configured")
        parts = dict(p.split("=", 1) for p in (sig_header or "").split(",") if "=" in p)
        try:
            ts = int(parts.get("t", "0"))
        except ValueError:
            ts = 0
        expected = hmac.new(self.stripe_webhook_secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
        sigs = [v for k, v in (p.split("=", 1) for p in sig_header.split(",") if "=" in p) if k == "v1"]
        if abs(time.time() - ts) > STRIPE_TOLERANCE_S or not any(hmac.compare_digest(expected, s) for s in sigs):
            raise HumanError("bad Stripe signature")
        ev = json.loads(payload)
        obj = (ev.get("data") or {}).get("object") or {}
        human_id = (obj.get("metadata") or {}).get("human_id") or obj.get("client_reference_id")
        if not human_id:
            return {"ignored": True}
        try:
            h = self.human(human_id)
        except HumanError:
            return {"ignored": True}
        if h["id_ref"] and obj.get("id") != h["id_ref"]:
            return {"ignored": True}                        # an older session; only the current one counts
        if ev.get("type") == "identity.verification_session.verified":
            self._mark(human_id, "verified", "stripe_identity", obj.get("id", ""))
        elif ev.get("type") == "identity.verification_session.canceled":
            self._mark(human_id, "failed", "stripe_identity", obj.get("id", ""))
        return {"human_id": human_id, "id_status": self.human(human_id)["id_status"]}

    def manual_verify(self, human_id: str, note: str = "") -> dict:
        self.human(human_id)
        self._mark(human_id, "verified", "manual", ("manual:" + (note or ""))[:120])
        return {"human_id": human_id, "id_status": "verified", "id_method": "manual"}

    def revoke_id(self, human_id: str) -> dict:
        self.human(human_id)
        self._mark(human_id, "none", "", "")
        return {"human_id": human_id, "id_status": "none"}


def _cose_bytes(ad: dict) -> bytes:
    """The exact COSE key bytes from the attested credential data."""
    raw = ad["cose_raw"]
    _, end = cbor_decode_prefix(raw, 0)
    return raw[:end]


# ---------------------------------------------------------------- the grade

GRADES = [("A+", 95), ("A", 85), ("B", 70), ("C", 55), ("D", 40), ("F", 0)]
LEVEL_POINTS = {"enrolled": 0, "quantum_aware": 10, "quantum_safe_identity": 20, "quantum_agent": 30,
                "quantum_agent_plus": 35}
KEY_POINTS = {"ML-DSA-44": 1, "ML-DSA-65": 3, "ML-DSA-87": 5}


def letter(score: int) -> str:
    return next(g for g, floor in GRADES if score >= floor)


def grade_parts(level: str, key_alg: str, cert_current: bool, human: dict, clean: bool, revoked: bool,
                impersonated: bool) -> dict:
    parts = {"quantum_level": LEVEL_POINTS.get(level, 0),
             "human_approval": 20 if human.get("human_approved") else 0,
             "id_verification": (25 if human.get("id_method") == "stripe_identity" else 15)
             if human.get("human_approved") and human.get("id_verified") else 0,
             "certificate_current": 10 if cert_current else 0,
             "key_strength": KEY_POINTS.get(key_alg, 0),
             "clean_record": 5 if clean else 0}
    score = sum(parts.values())
    if impersonated:
        score = max(0, score - 15)
    if revoked:
        score = 0
    return {"score": score, "grade": letter(score), "points": parts,
            "penalties": [p for p, on in (("revoked", revoked), ("impersonation_attempts", impersonated)) if on]}
