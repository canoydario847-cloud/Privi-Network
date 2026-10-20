"""Privi Mandates: signed proof that a human authorized an AI agent to spend.

An organization's agent drafts a mandate (budget, per-payment cap, allowed payees,
expiry, purpose). The human principal signs the plain-English terms with their wallet
(EIP-191). From then on any merchant, payment facilitator or counterparty can check a
proposed payment against the mandate for free, and the agent records each spend so the
remaining budget is enforced. The principal can revoke with one more signature.

The mandate hash is anchored on the Privi chain and every activation, spend and
revocation is written to the organization's tamper-evident log.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .kya import checksum, norm_address, personal_hash, recover_address

MAX_DAYS = 365
DRAFT_TTL_HOURS = 72

SCHEMA = """
CREATE TABLE IF NOT EXISTS mandates (
    mandate_id    TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL,
    stream_id     TEXT NOT NULL,
    principal     TEXT NOT NULL,          -- lowercase 0x wallet of the human
    agent_wallet  TEXT,                   -- optional lowercase 0x wallet the agent pays from
    max_total     INTEGER NOT NULL,       -- micro-USDC
    max_per_tx    INTEGER NOT NULL,
    payees        TEXT NOT NULL,          -- JSON list; empty = any payee
    purpose       TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    message       TEXT NOT NULL,          -- exact text the principal signs
    terms_hash    TEXT NOT NULL,
    status        TEXT NOT NULL,          -- draft | active | revoked | expired
    signature     TEXT,
    privi_signature TEXT,
    anchor        TEXT,
    spent         INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    activated_at  TEXT,
    revoked_at    TEXT,
    revoke_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_mandates_org ON mandates (org_id, created_at);
CREATE TABLE IF NOT EXISTS mandate_spends (
    spend_id    TEXT PRIMARY KEY,
    mandate_id  TEXT NOT NULL,
    amount      INTEGER NOT NULL,
    payee       TEXT NOT NULL,
    reference   TEXT NOT NULL DEFAULT '',
    entry_hash  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spends_mandate ON mandate_spends (mandate_id, created_at);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def to_micro(usd: str | float | int) -> int:
    try:
        d = Decimal(str(usd).strip().lstrip("$"))
    except InvalidOperation:
        raise MandateError(f"not an amount: {usd}")
    if d <= 0 or d.as_tuple().exponent < -6:
        raise MandateError(f"amount must be positive with at most 6 decimals: {usd}")
    return int(d * 1_000_000)


def fmt(micro: int) -> str:
    s = f"{Decimal(micro) / Decimal(1_000_000):f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def norm_payee(p: str) -> str:
    p = (p or "").strip().lower()
    if p.startswith("0x"):
        return norm_address(p)
    p = p.removeprefix("https://").removeprefix("http://").split("/")[0]
    if not p or " " in p or len(p) > 253:
        raise MandateError(f"payee must be a 0x address or a domain: {p!r}")
    return p


class MandateError(Exception):
    pass


class Mandates:
    def __init__(self, db: sqlite3.Connection, lock: threading.Lock, passports, issuer_url: str):
        self._db, self._lock, self.passports, self.issuer_url = db, lock, passports, issuer_url
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # ---------------- lifecycle ----------------

    def draft(self, org: dict, stream_id: str, principal: str, max_total: str, max_per_tx: str | None,
              payees: list[str] | None, days: int, purpose: str, agent_wallet: str | None) -> dict:
        principal = norm_address(principal)
        agent = norm_address(agent_wallet) if agent_wallet else None
        total = to_micro(max_total)
        per = to_micro(max_per_tx) if max_per_tx else total
        if per > total:
            raise MandateError("max_per_payment cannot exceed max_total")
        if not 1 <= days <= MAX_DAYS:
            raise MandateError(f"days must be between 1 and {MAX_DAYS}")
        plist = sorted({norm_payee(p) for p in (payees or []) if p and p.strip()})
        purpose = " ".join((purpose or "").split())[:300]
        if not purpose:
            raise MandateError("purpose is required: say what the agent may spend on")
        mid = "mdt_" + secrets.token_hex(8)
        expires = _iso(_now() + timedelta(days=days))
        who = f"{org['name']}'s agent '{stream_id}'" + (f" (wallet {checksum(agent)})" if agent else "")
        to = "any payee" if not plist else "only these payees: " + ", ".join(
            checksum(p) if p.startswith("0x") else p for p in plist)
        msg = (f"Privi Mandate {mid}\n"
               f"I, {checksum(principal)}, authorize {who} to spend up to {fmt(total)} USDC in total, "
               f"at most {fmt(per)} USDC per payment, to {to}, until {expires} UTC.\n"
               f"Purpose: {purpose}\n"
               f"I can revoke this at any time. Issued via Privi Ledger ({org['org_id']}).")
        th = hashlib.sha256(msg.encode("utf-8")).hexdigest()
        with self._lock:
            self._db.execute(
                "INSERT INTO mandates (mandate_id, org_id, stream_id, principal, agent_wallet, max_total, max_per_tx, "
                "payees, purpose, expires_at, message, terms_hash, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, org["org_id"], stream_id, principal, agent, total, per, json.dumps(plist), purpose, expires,
                 msg, th, "draft", _iso(_now())))
            self._db.commit()
        return self.public(mid)

    def activate(self, mid: str, signature: str) -> dict:
        m = self._row(mid)
        if not m:
            raise MandateError("no such mandate")
        if m["status"] != "draft":
            raise MandateError(f"mandate is already {m['status']}")
        if m["created_at"] < _iso(_now() - timedelta(hours=DRAFT_TTL_HOURS)):
            raise MandateError("draft expired; ask the agent for a new mandate")
        try:
            signer = recover_address(personal_hash(m["message"]), bytes.fromhex(signature.strip().removeprefix("0x")))
        except ValueError as e:
            raise MandateError(f"bad signature: {e}")
        if signer != m["principal"]:
            raise MandateError(f"signed by {checksum(signer)}, but the mandate names {checksum(m['principal'])}")
        privi_sig = self.passports.sign(m["terms_hash"])
        with self._lock:
            self._db.execute("UPDATE mandates SET status='active', signature=?, privi_signature=?, activated_at=? "
                             "WHERE mandate_id=? AND status='draft'", (signature.strip(), privi_sig, _iso(_now()), mid))
            self._db.commit()
        return self.public(mid)

    def set_anchor(self, mid: str, att: dict) -> None:
        with self._lock:
            self._db.execute("UPDATE mandates SET anchor=? WHERE mandate_id=?", (json.dumps(att), mid))
            self._db.commit()

    def revoke(self, mid: str, reason: str, *, org_id: str | None = None, signature: str | None = None) -> dict:
        m = self._row(mid)
        if not m:
            raise MandateError("no such mandate")
        if signature:
            msg = f"Revoke Privi Mandate {mid}"
            try:
                signer = recover_address(personal_hash(msg), bytes.fromhex(signature.strip().removeprefix("0x")))
            except ValueError as e:
                raise MandateError(f"bad signature: {e}")
            if signer != m["principal"]:
                raise MandateError("only the principal who signed the mandate can revoke it by signature")
        elif org_id != m["org_id"]:
            raise MandateError("no such mandate for this organization")
        if m["status"] == "revoked":
            return self.public(mid)
        with self._lock:
            self._db.execute("UPDATE mandates SET status='revoked', revoked_at=?, revoke_reason=? WHERE mandate_id=?",
                             (_iso(_now()), (reason or "")[:300], mid))
            self._db.commit()
        return self.public(mid)

    # ---------------- checks and spends ----------------

    def _decide(self, m: dict, amount: int, payee: str) -> list[str]:
        reasons = []
        status = self._status(m)
        if status != "active":
            reasons.append({"draft": "the principal has not signed this mandate yet",
                            "revoked": "the principal revoked this mandate",
                            "expired": "this mandate has expired"}.get(status, f"mandate is {status}"))
        if amount > m["max_per_tx"]:
            reasons.append(f"{fmt(amount)} USDC is over the per-payment limit of {fmt(m['max_per_tx'])} USDC")
        if amount > m["max_total"] - m["spent"]:
            reasons.append(f"{fmt(amount)} USDC is over the remaining budget of {fmt(m['max_total'] - m['spent'])} USDC")
        payees = json.loads(m["payees"])
        if payees and payee not in payees:
            reasons.append(f"payee {payee} is not on the mandate's allowed list")
        return reasons

    def check(self, mid: str, amount: str, payee: str) -> dict:
        m = self._row(mid)
        if not m:
            return {"mandate_id": mid, "allow": False, "reasons": ["no such mandate"]}
        a, p = to_micro(amount), norm_payee(payee)
        reasons = self._decide(m, a, p)
        out = {"mandate_id": mid, "allow": not reasons, "reasons": reasons, "amount_usdc": fmt(a), "payee": p,
               "remaining_usdc": fmt(m["max_total"] - m["spent"]), "expires_at": m["expires_at"],
               "principal": checksum(m["principal"]), "org_id": m["org_id"], "stream_id": m["stream_id"],
               "principal_signature_valid": self._sig_ok(m)}
        if not out["principal_signature_valid"] and self._status(m) == "active":
            out["allow"], out["reasons"] = False, out["reasons"] + ["principal signature does not verify"]
        body = {"type": "PriviMandateCheck", "version": "1", "issuer_url": self.issuer_url,
                "key_id": self.passports.key_id, "mandate_id": mid, "terms_hash": m["terms_hash"],
                "allow": out["allow"], "amount_usdc": out["amount_usdc"], "payee": p,
                "remaining_usdc": out["remaining_usdc"], "checked_at": _iso(_now())}
        h = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        out.update(attestation=body, attestation_hash=h, signature=self.passports.sign(h))
        return out

    def spend(self, mid: str, org_id: str, amount: str, payee: str, reference: str) -> dict:
        a, p = to_micro(amount), norm_payee(payee)
        with self._lock:
            r = self._db.execute("SELECT * FROM mandates WHERE mandate_id=?", (mid,)).fetchone()
            if not r or r["org_id"] != org_id:
                raise MandateError("no such mandate for this organization")
            m = dict(r)
            reasons = self._decide(m, a, p)
            if not reasons and not self._sig_ok(m):
                reasons = ["principal signature does not verify"]
            if reasons:
                raise MandateError("; ".join(reasons))
            sid = "spd_" + secrets.token_hex(8)
            self._db.execute("UPDATE mandates SET spent = spent + ? WHERE mandate_id=?", (a, mid))
            self._db.execute("INSERT INTO mandate_spends (spend_id, mandate_id, amount, payee, reference, created_at) "
                             "VALUES (?,?,?,?,?,?)", (sid, mid, a, p, reference[:200], _iso(_now())))
            self._db.commit()
        return {"spend_id": sid, "mandate_id": mid, "amount_usdc": fmt(a), "payee": p,
                "remaining_usdc": fmt(m["max_total"] - m["spent"] - a)}

    def attach_entry(self, spend_id: str, entry_hash: str) -> None:
        with self._lock:
            self._db.execute("UPDATE mandate_spends SET entry_hash=? WHERE spend_id=?", (entry_hash, spend_id))
            self._db.commit()

    # ---------------- views ----------------

    def _row(self, mid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM mandates WHERE mandate_id=?", ((mid or "").strip(),)).fetchone()
        return dict(r) if r else None

    @staticmethod
    def _status(m: dict) -> str:
        if m["status"] == "active" and m["expires_at"] < _iso(_now()):
            return "expired"
        return m["status"]

    @staticmethod
    def _sig_ok(m: dict) -> bool:
        if not m.get("signature"):
            return False
        try:
            return recover_address(personal_hash(m["message"]),
                                   bytes.fromhex(m["signature"].removeprefix("0x"))) == m["principal"]
        except ValueError:
            return False

    def public(self, mid: str) -> dict:
        m = self._row(mid)
        if not m:
            raise MandateError("no such mandate")
        spends = [dict(r) for r in self._db.execute(
            "SELECT spend_id, amount, payee, reference, entry_hash, created_at FROM mandate_spends WHERE mandate_id=? "
            "ORDER BY created_at DESC LIMIT 50", (mid,)).fetchall()]
        for s in spends:
            s["amount_usdc"] = fmt(s.pop("amount"))
        return {
            "mandate_id": mid, "status": self._status(m), "org_id": m["org_id"], "stream_id": m["stream_id"],
            "principal": checksum(m["principal"]),
            "agent_wallet": checksum(m["agent_wallet"]) if m["agent_wallet"] else None,
            "max_total_usdc": fmt(m["max_total"]), "max_per_payment_usdc": fmt(m["max_per_tx"]),
            "spent_usdc": fmt(m["spent"]), "remaining_usdc": fmt(m["max_total"] - m["spent"]),
            "payees": json.loads(m["payees"]) or "any", "purpose": m["purpose"], "expires_at": m["expires_at"],
            "message": m["message"], "terms_hash": m["terms_hash"],
            "principal_signature": m["signature"], "principal_signature_valid": self._sig_ok(m),
            "privi_signature": m["privi_signature"], "anchor": json.loads(m["anchor"]) if m["anchor"] else None,
            "created_at": m["created_at"], "activated_at": m["activated_at"],
            "revoked_at": m["revoked_at"], "revoke_reason": m["revoke_reason"],
            "sign_url": f"{self.issuer_url}/mandates/{mid}/sign", "spends": spends,
        }

    def list_for(self, org_id: str) -> list[dict]:
        rows = self._db.execute("SELECT mandate_id FROM mandates WHERE org_id=? ORDER BY created_at DESC LIMIT 100",
                                (org_id,)).fetchall()
        out = []
        for r in rows:
            p = self.public(r["mandate_id"])
            out.append({k: p[k] for k in ("mandate_id", "status", "stream_id", "principal", "max_total_usdc",
                                          "spent_usdc", "remaining_usdc", "expires_at", "purpose")})
        return out
