"""Privi KYA: Know-Your-Agent for blockchain wallets.

As AI agents become the main senders of on-chain transactions, every chain, DeFi
protocol, exchange, stablecoin issuer and x402 facilitator needs an answer to one
question before accepting a transaction: *is this wallet operated by an audited
agent, and how trustworthy is it right now?*

Privi KYA answers it. An organization binds a wallet address to its Privi
Passport by signing a Privi challenge with that wallet (EIP-191 personal_sign,
recovered here in pure Python - no web3 dependency). Anyone can then check the
address for free and get the live Passport verdict, plus a short-lived KYA
attestation signed by Privi that a facilitator can cache and check offline.

Only Privi can issue a KYA verdict because only Privi issues Passports.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

CHALLENGE_TTL_MIN = 30
ATTESTATION_TTL_MIN = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS kya_challenges (
    challenge_id TEXT PRIMARY KEY,
    org_id       TEXT NOT NULL,
    address      TEXT NOT NULL,
    message      TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    used_at      TEXT
);
CREATE TABLE IF NOT EXISTS kya_bindings (
    address      TEXT PRIMARY KEY,              -- lowercase 0x...
    org_id       TEXT NOT NULL,
    stream_id    TEXT NOT NULL,                 -- '*' or the agent stream it represents
    label        TEXT NOT NULL DEFAULT '',
    proof        TEXT NOT NULL,                 -- 'signature' | 'declared'
    proof_detail TEXT NOT NULL DEFAULT '{}',
    bound_at     TEXT NOT NULL,
    revoked_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_kya_org ON kya_bindings (org_id);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


# ---------------------------------------------------------------- keccak-256 (FIPS-202 permutation, Ethereum padding)

_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
       0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
       0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
       0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x: int, n: int) -> int:
    return ((x << n) | (x >> (64 - n))) & _M


def _keccak_f(a: list[list[int]]) -> None:
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                a[x][y] ^= d[x]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        for x in range(5):
            for y in range(5):
                a[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])
        a[0][0] ^= rc


def keccak256(data: bytes) -> bytes:
    rate = 136
    a = [[0] * 5 for _ in range(5)]
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * ((-len(msg)) % rate)
    msg[-1] |= 0x80
    for off in range(0, len(msg), rate):
        block = msg[off:off + rate]
        for i in range(rate // 8):
            a[i % 5][i // 5] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        _keccak_f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(rate // 8))
    return out[:32]


# ---------------------------------------------------------------- secp256k1 public-key recovery

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _inv(a: int, m: int) -> int:
    return pow(a, -1, m)


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % _P == 0:
        return None
    if p == q:
        lam = (3 * p[0] * p[0]) * _inv(2 * p[1], _P) % _P
    else:
        lam = (q[1] - p[1]) * _inv(q[0] - p[0], _P) % _P
    x = (lam * lam - p[0] - q[0]) % _P
    return (x, (lam * (p[0] - x) - p[1]) % _P)


def _mul(k: int, p):
    r = None
    while k:
        if k & 1:
            r = _add(r, p)
        p = _add(p, p)
        k >>= 1
    return r


def recover_address(msg_hash: bytes, sig: bytes) -> str:
    """Ethereum address that produced a 65-byte (r, s, v) signature over msg_hash."""
    if len(sig) != 65:
        raise ValueError("signature must be 65 bytes")
    r, s, v = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:64], "big"), sig[64]
    if v >= 27:
        v -= 27
    if v not in (0, 1) or not (0 < r < _N and 0 < s < _N):
        raise ValueError("invalid signature values")
    x = r
    y_sq = (pow(x, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != y_sq:
        raise ValueError("invalid signature point")
    if (y & 1) != v:
        y = _P - y
    e = int.from_bytes(msg_hash, "big")
    rinv = _inv(r, _N)
    q = _add(_mul(s * rinv % _N, (x, y)), _mul((-e * rinv) % _N, _G))
    if q is None:
        raise ValueError("invalid signature")
    pub = q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big")
    return "0x" + keccak256(pub)[-20:].hex()


def personal_hash(message: str) -> bytes:
    data = message.encode("utf-8")
    return keccak256(b"\x19Ethereum Signed Message:\n" + str(len(data)).encode() + data)


def checksum(address: str) -> str:
    a = address.lower().removeprefix("0x")
    h = keccak256(a.encode()).hex()
    return "0x" + "".join(c.upper() if int(h[i], 16) >= 8 else c for i, c in enumerate(a))


def norm_address(address: str) -> str:
    a = (address or "").strip().lower()
    if not (a.startswith("0x") and len(a) == 42 and all(c in "0123456789abcdef" for c in a[2:])):
        raise ValueError("address must be a 0x-prefixed 20-byte hex address")
    return a


# ---------------------------------------------------------------- store

class KYAError(Exception):
    pass


class KYA:
    def __init__(self, db: sqlite3.Connection, lock: threading.Lock, passports, issuer_url: str):
        self._db, self._lock, self.passports, self.issuer_url = db, lock, passports, issuer_url
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def challenge(self, org_id: str, org_name: str, address: str) -> dict:
        addr = norm_address(address)
        cid = "kyc_" + secrets.token_hex(6)
        exp = _iso(_now() + timedelta(minutes=CHALLENGE_TTL_MIN))
        msg = (f"Privi KYA: I confirm that wallet {checksum(addr)} is operated by {org_name} ({org_id}) "
               f"and may be bound to its Privi Passport.\nChallenge: {cid}\nExpires: {exp}")
        with self._lock:
            self._db.execute("INSERT INTO kya_challenges VALUES (?,?,?,?,?,NULL)", (cid, org_id, addr, msg, exp))
            self._db.commit()
        return {"challenge_id": cid, "address": checksum(addr), "message": msg, "expires_at": exp,
                "how": "Sign 'message' with the wallet (EIP-191 personal_sign / eth_sign), then call kya_bind_wallet "
                       "with the challenge_id and the 65-byte hex signature."}

    def bind(self, org_id: str, address: str, stream_id: str, label: str, challenge_id: str | None,
             signature: str | None) -> dict:
        addr = norm_address(address)
        detail: dict[str, Any] = {}
        if signature:
            if not challenge_id:
                raise KYAError("a challenge_id is required with a signature; call kya_challenge first")
            with self._lock:
                c = self._db.execute("SELECT * FROM kya_challenges WHERE challenge_id=?", (challenge_id.strip(),)).fetchone()
            if not c or c["org_id"] != org_id or c["address"] != addr:
                raise KYAError("challenge does not match this organization and address")
            if c["used_at"]:
                raise KYAError("challenge already used")
            if c["expires_at"] < _iso(_now()):
                raise KYAError("challenge expired; request a new one")
            try:
                sig = bytes.fromhex(signature.strip().removeprefix("0x"))
                recovered = recover_address(personal_hash(c["message"]), sig)
            except ValueError as e:
                raise KYAError(f"bad signature: {e}")
            if recovered != addr:
                raise KYAError(f"signature was made by {checksum(recovered)}, not {checksum(addr)}")
            proof = "signature"
            detail = {"challenge_id": challenge_id, "scheme": "EIP-191 personal_sign", "message_hash": personal_hash(c["message"]).hex()}
            with self._lock:
                self._db.execute("UPDATE kya_challenges SET used_at=? WHERE challenge_id=?", (_iso(_now()), challenge_id))
                self._db.commit()
        else:
            proof = "declared"
        with self._lock:
            existing = self._db.execute("SELECT org_id, revoked_at FROM kya_bindings WHERE address=?", (addr,)).fetchone()
            if existing and existing["org_id"] != org_id and not existing["revoked_at"]:
                if proof != "signature":
                    raise KYAError("this wallet is bound to another organization; a wallet signature is required to rebind it")
            self._db.execute("INSERT OR REPLACE INTO kya_bindings VALUES (?,?,?,?,?,?,?,NULL)",
                             (addr, org_id, stream_id or "*", label[:120], proof, json.dumps(detail), _iso(_now())))
            self._db.commit()
        return self.binding(addr)

    def unbind(self, org_id: str, address: str) -> dict:
        addr = norm_address(address)
        with self._lock:
            b = self._db.execute("SELECT org_id FROM kya_bindings WHERE address=?", (addr,)).fetchone()
            if not b or b["org_id"] != org_id:
                raise KYAError("no binding for this wallet in your organization")
            self._db.execute("UPDATE kya_bindings SET revoked_at=? WHERE address=?", (_iso(_now()), addr))
            self._db.commit()
        return {"address": checksum(addr), "unbound": True}

    def binding(self, address: str) -> dict | None:
        r = self._db.execute("SELECT * FROM kya_bindings WHERE address=?", (norm_address(address),)).fetchone()
        if not r:
            return None
        return {"address": checksum(r["address"]), "org_id": r["org_id"], "stream_id": r["stream_id"], "label": r["label"],
                "proof": r["proof"], "proof_detail": json.loads(r["proof_detail"]), "bound_at": r["bound_at"],
                "revoked_at": r["revoked_at"]}

    def list_for(self, org_id: str) -> list[dict]:
        rows = self._db.execute("SELECT address FROM kya_bindings WHERE org_id=? ORDER BY bound_at DESC", (org_id,)).fetchall()
        return [self.binding(r["address"]) for r in rows]

    def check(self, address: str, min_score: int, min_grade: str | None, require_signed: bool) -> dict:
        """The KYA verdict for a wallet: bound? proven? which org? what does its live Passport say?"""
        addr = norm_address(address)
        out: dict[str, Any] = {"address": checksum(addr), "known": False, "allow": False, "reasons": []}
        b = self.binding(addr)
        if not b or b["revoked_at"]:
            out["reasons"].append("wallet is not bound to any Privi Passport" if not b else "binding was revoked")
            return out
        out.update(known=True, org_id=b["org_id"], stream_id=b["stream_id"], label=b["label"], proof=b["proof"],
                   bound_at=b["bound_at"])
        org = self._db.execute("SELECT org_id, name FROM orgs WHERE org_id=?", (b["org_id"],)).fetchone()
        out["organization"] = org["name"] if org else None
        if require_signed and b["proof"] != "signature":
            out["reasons"].append("wallet ownership was declared, not proven by signature")
        sid = None if b["stream_id"] == "*" else b["stream_id"]
        row = self._db.execute(
            "SELECT passport_id FROM passports WHERE org_id=? AND stream_id=? AND revoked_at IS NULL AND expires_at>? "
            "ORDER BY created_at DESC LIMIT 1", (b["org_id"], b["stream_id"], _iso(_now()))).fetchone()
        for scope in ("stream_id='*'", "1=1"):   # fall back to the org passport, then to any valid passport
            if row:
                break
            row = self._db.execute(
                f"SELECT passport_id FROM passports WHERE org_id=? AND {scope} AND revoked_at IS NULL AND expires_at>? "
                "ORDER BY created_at DESC LIMIT 1", (b["org_id"], _iso(_now()))).fetchone()
        if not row:
            out["reasons"].append("organization has no valid Privi Passport; it should call passport_issue")
            return out
        rec = self.passports.get(row["passport_id"])
        v = self.passports.check(rec)
        g = self.passports.gate(v, min_score, min_grade, True, False)
        out.update(passport_id=rec["passport_id"], current_score=g["current_score"], current_grade=g["current_grade"],
                   passport_valid=v["valid"], history_still_intact=v.get("history_still_intact"))
        out["reasons"] += g["reasons"]
        out["allow"] = not out["reasons"]
        _ = sid
        return out

    def attest(self, verdict: dict) -> dict:
        """Short-lived, Privi-signed statement of a verdict, for facilitators that want to cache it."""
        body = {"type": "PriviKYA", "version": "1", "issuer": "Privi Ledger", "issuer_url": self.issuer_url,
                "key_id": self.passports.key_id, "address": verdict["address"], "allow": verdict["allow"],
                "known": verdict["known"], "org_id": verdict.get("org_id"), "passport_id": verdict.get("passport_id"),
                "current_score": verdict.get("current_score"), "current_grade": verdict.get("current_grade"),
                "proof": verdict.get("proof"), "issued_at": _iso(_now()),
                "expires_at": _iso(_now() + timedelta(minutes=ATTESTATION_TTL_MIN))}
        canon = json.dumps(body, sort_keys=True, separators=(",", ":"))
        h = hashlib.sha256(canon.encode()).hexdigest()
        return {"attestation": body, "attestation_hash": h, "signature": self.passports.sign(h),
                "verify": "sha256(canonical JSON) must equal attestation_hash; Ed25519-verify signature with the issuer key "
                          "at /.well-known/privi-passport.json"}
