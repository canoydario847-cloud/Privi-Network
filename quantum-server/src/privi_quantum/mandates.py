# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Quantum Mandates: a human's signed permission for an AI agent to spend on quantum hardware.

An agent drafts the terms: total budget, a cap per job, which backends and problems, the most shots per
job, and an expiry. The person who approved that agent signs the exact terms with their passkey (Face ID,
Touch ID, Windows Hello or screen lock, checked on their own device). Budgets above a threshold also need
that person's government ID to be verified. From then on every paid quantum run must name an active
mandate and carry the agent's Privi Inspector pass; Privi checks the run against the terms, records the
spend, refunds jobs the provider fails, and the person or the agent can revoke it at any time.

The signed mandate and any revocation are sealed as Privi Quantum attestations (Ed25519 + ML-DSA-87)
and anchored on chain like every other Privi Quantum result.
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

MAX_DAYS = 365
DRAFT_TTL_HOURS = 72
MAX_BUDGET_USD = Decimal("100000")
MAX_SHOTS = 10000

SCHEMA = """
CREATE TABLE IF NOT EXISTS qmandates (
    mandate_id    TEXT PRIMARY KEY,
    agent_id      TEXT NOT NULL,
    human_id      TEXT NOT NULL,          -- the person who approved the agent; only they can sign
    budget        INTEGER NOT NULL,       -- micro-USD
    per_job       INTEGER NOT NULL,
    backends      TEXT NOT NULL,          -- JSON list; empty = any paid backend
    problems      TEXT NOT NULL,          -- JSON list; empty = any problem
    max_shots     INTEGER NOT NULL,
    purpose       TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    message       TEXT NOT NULL,          -- exact plain-English terms the person signs
    terms_hash    TEXT NOT NULL,
    status        TEXT NOT NULL,          -- draft | active | revoked
    credential_id TEXT,
    attestation_id TEXT,
    spent         INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    activated_at  TEXT,
    revoked_at    TEXT,
    revoked_by    TEXT,
    revoke_reason TEXT,
    revocation_attestation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_qmandates_agent ON qmandates (agent_id, created_at);
CREATE TABLE IF NOT EXISTS qmandate_spends (
    job_id      TEXT PRIMARY KEY,
    mandate_id  TEXT NOT NULL,
    backend_id  TEXT NOT NULL,
    shots       INTEGER NOT NULL,
    amount      INTEGER NOT NULL,         -- micro-USD
    status      TEXT NOT NULL,            -- charged | refunded
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qspends_mandate ON qmandate_spends (mandate_id, created_at);
"""


class MandateError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime | None = None) -> str:
    return (d or _now()).isoformat(timespec="seconds")


def to_micro(usd: Any, what: str) -> int:
    try:
        d = Decimal(str(usd).strip().lstrip("$"))
    except InvalidOperation:
        raise MandateError(f"{what} is not an amount: {usd}")
    if d <= 0 or d > MAX_BUDGET_USD:
        raise MandateError(f"{what} must be more than $0 and at most ${MAX_BUDGET_USD}")
    return int((d * 1_000_000).to_integral_value())


def usd(micro: int) -> str:
    return f"${Decimal(micro) / 1_000_000:.2f}" if micro % 10_000 == 0 else f"${Decimal(micro) / 1_000_000:.6f}".rstrip("0")


class QuantumMandates:
    def __init__(self, db_path: str, id_required_over_usd: float = 100.0):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self.id_required_over = int(Decimal(str(id_required_over_usd)) * 1_000_000)

    # ---------------- drafting and signing ----------------

    def draft(self, agent: dict, human_id: str, budget_usd: Any, max_per_job_usd: Any | None, backends: list[str] | None,
              problems: list[str] | None, max_shots: int, days: int, purpose: str,
              known_backends: dict[str, str], known_problems: list[str]) -> dict:
        budget = to_micro(budget_usd, "budget_usd")
        per_job = to_micro(max_per_job_usd, "max_per_job_usd") if max_per_job_usd not in (None, "") else budget
        if per_job > budget:
            raise MandateError("max_per_job_usd cannot be more than budget_usd")
        if not 1 <= int(days) <= MAX_DAYS:
            raise MandateError(f"days must be 1-{MAX_DAYS}")
        if not 1 <= int(max_shots) <= MAX_SHOTS:
            raise MandateError(f"max_shots must be 1-{MAX_SHOTS}")
        bks = sorted({b.strip() for b in (backends or []) if b and b.strip()})
        for b in bks:
            if b not in known_backends:
                raise MandateError(f"unknown backend {b}; see quantum_backends")
        probs = sorted({p.strip() for p in (problems or []) if p and p.strip()})
        for p in probs:
            if p not in known_problems:
                raise MandateError(f"unknown problem {p}; choose from {', '.join(known_problems)}")
        purpose = " ".join(str(purpose or "").split())[:300]
        if len(purpose) < 3:
            raise MandateError("say what the quantum runs are for (purpose)")
        mid = "qm_" + secrets.token_hex(8)
        expires = _now() + timedelta(days=int(days))
        lines = [
            "Privi Quantum Mandate",
            f"Mandate: {mid}",
            f"I authorize the AI agent {agent['name']} ({agent['agent_id']}), operated by {agent['operator']},",
            "to run paid quantum computing jobs through Privi Quantum on my behalf, within these limits:",
            f"- Total budget: {usd(budget)}",
            f"- Most per job: {usd(per_job)}",
            "- Backends: " + (", ".join(f"{b} ({known_backends[b]})" for b in bks) if bks else "any paid backend Privi offers"),
            "- Problems: " + (", ".join(probs) if probs else "any"),
            f"- Most shots per job: {int(max_shots)}",
            f"- Expires: {_iso(expires)}",
            f"- Purpose: {purpose}",
            "I can revoke this mandate at any time.",
        ]
        message = "\n".join(lines)
        th = hashlib.sha256(message.encode()).hexdigest()
        with self._lock:
            self._db.execute(
                "INSERT INTO qmandates (mandate_id, agent_id, human_id, budget, per_job, backends, problems, max_shots, purpose, "
                "expires_at, message, terms_hash, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'draft',?)",
                (mid, agent["agent_id"], human_id, budget, per_job, json.dumps(bks), json.dumps(probs), int(max_shots), purpose,
                 _iso(expires), message, th, _iso()))
            self._db.commit()
        return self.public(mid)

    def needs_id(self, m: dict) -> bool:
        return m["budget"] > self.id_required_over

    def challenge(self, mid: str, action: str) -> bytes:
        """What the passkey signs: the exact terms (by hash), this mandate and the action."""
        m = self._row(mid)
        if not m:
            raise MandateError("unknown mandate")
        if action not in ("sign", "revoke"):
            raise MandateError("action must be sign or revoke")
        return hashlib.sha256(f"privi-quantum-mandate:v1:{action}:{mid}:{m['terms_hash']}".encode()).digest()

    def activate(self, mid: str, human_id: str, credential_id: str, id_verified: bool) -> dict:
        m = self._row(mid)
        if not m:
            raise MandateError("unknown mandate")
        if m["status"] != "draft":
            raise MandateError(f"mandate is already {m['status']}")
        if datetime.fromisoformat(m["created_at"]) + timedelta(hours=DRAFT_TTL_HOURS) < _now():
            raise MandateError("this draft expired; ask the agent for a new one")
        if human_id != m["human_id"]:
            raise MandateError("only the person who approved this agent can sign its mandate")
        if self.needs_id(m) and not id_verified:
            raise MandateError(f"budgets over {usd(self.id_required_over)} need your government ID verified first")
        with self._lock:
            self._db.execute("UPDATE qmandates SET status='active', credential_id=?, activated_at=? WHERE mandate_id=? AND status='draft'",
                             (credential_id, _iso(), mid))
            self._db.commit()
        return self._row(mid)

    def set_attestation(self, mid: str, aid: str, field: str = "attestation_id") -> None:
        assert field in ("attestation_id", "revocation_attestation_id")
        with self._lock:
            self._db.execute(f"UPDATE qmandates SET {field}=? WHERE mandate_id=?", (aid, mid))
            self._db.commit()

    def revoke(self, mid: str, by: str, reason: str) -> dict:
        m = self._row(mid)
        if not m:
            raise MandateError("unknown mandate")
        if m["status"] == "revoked":
            raise MandateError("mandate is already revoked")
        with self._lock:
            self._db.execute("UPDATE qmandates SET status='revoked', revoked_at=?, revoked_by=?, revoke_reason=? WHERE mandate_id=?",
                             (_iso(), by, " ".join(str(reason or "").split())[:200], mid))
            self._db.commit()
        return self._row(mid)

    # ---------------- enforcement ----------------

    def decide(self, mid: str, agent_id: str | None, backend_id: str, est_usd: float, shots: int, problem: str) -> dict:
        """Would this paid run be allowed under the mandate? Returns {allowed, reasons, remaining...}."""
        m = self._row(mid)
        if not m:
            return {"allowed": False, "reasons": ["unknown mandate"]}
        reasons: list[str] = []
        st = self._status(m)
        if st != "active":
            reasons.append({"draft": "mandate is not signed yet: the person must sign it at sign_url",
                            "revoked": "mandate was revoked", "expired": "mandate expired"}[st])
        if agent_id is not None and agent_id != m["agent_id"]:
            reasons.append("this mandate belongs to a different agent")
        amount = int(Decimal(str(est_usd)) * 1_000_000)
        bks, probs = json.loads(m["backends"]), json.loads(m["problems"])
        if bks and backend_id not in bks:
            reasons.append(f"backend {backend_id} is not allowed by this mandate (allowed: {', '.join(bks)})")
        if probs and problem not in probs:
            reasons.append(f"problem {problem} is not allowed by this mandate")
        if shots > m["max_shots"]:
            reasons.append(f"{shots} shots is more than the mandate allows ({m['max_shots']})")
        if amount > m["per_job"]:
            reasons.append(f"estimated {usd(amount)} is more than the per-job cap {usd(m['per_job'])}")
        if amount > m["budget"] - m["spent"]:
            reasons.append(f"estimated {usd(amount)} is more than the {usd(m['budget'] - m['spent'])} left in the budget")
        return {"allowed": not reasons, "reasons": reasons, "mandate_id": mid, "status": st,
                "estimated_usd": float(est_usd), "remaining_usd": (m["budget"] - m["spent"]) / 1_000_000,
                "per_job_cap_usd": m["per_job"] / 1_000_000}

    def charge(self, mid: str, agent_id: str, job_id: str, backend_id: str, shots: int, est_usd: float, problem: str) -> dict:
        """Re-check under the lock and record the spend, so two runs can never overspend the budget together."""
        with self._lock:
            d = self.decide(mid, agent_id, backend_id, est_usd, shots, problem)
            if not d["allowed"]:
                raise MandateError("; ".join(d["reasons"]))
            amount = int(Decimal(str(est_usd)) * 1_000_000)
            self._db.execute("INSERT INTO qmandate_spends VALUES (?,?,?,?,?,'charged',?)",
                             (job_id, mid, backend_id, shots, amount, _iso()))
            self._db.execute("UPDATE qmandates SET spent=spent+? WHERE mandate_id=?", (amount, mid))
            self._db.commit()
        return {"mandate_id": mid, "charged_usd": amount / 1_000_000,
                "remaining_usd": (self._row(mid)["budget"] - self._row(mid)["spent"]) / 1_000_000}

    def bind_job(self, reservation_id: str, job_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE qmandate_spends SET job_id=? WHERE job_id=?", (job_id, reservation_id))
            self._db.commit()

    def refund(self, job_id: str) -> int:
        """Give the money back to the mandate when the provider fails or cancels a job. Returns micro-USD refunded."""
        with self._lock:
            r = self._db.execute("SELECT * FROM qmandate_spends WHERE job_id=? AND status='charged'", (job_id,)).fetchone()
            if not r:
                return 0
            self._db.execute("UPDATE qmandate_spends SET status='refunded' WHERE job_id=?", (job_id,))
            self._db.execute("UPDATE qmandates SET spent=MAX(0, spent-?) WHERE mandate_id=?", (r["amount"], r["mandate_id"]))
            self._db.commit()
            return r["amount"]

    def spend_for_job(self, job_id: str) -> dict | None:
        r = self._db.execute("SELECT * FROM qmandate_spends WHERE job_id=?", (job_id,)).fetchone()
        return dict(r) if r else None

    # ---------------- views ----------------

    def _row(self, mid: str) -> dict | None:
        r = self._db.execute("SELECT * FROM qmandates WHERE mandate_id=?", (str(mid)[:40],)).fetchone()
        return dict(r) if r else None

    @staticmethod
    def _status(m: dict) -> str:
        if m["status"] == "active" and datetime.fromisoformat(m["expires_at"]) <= _now():
            return "expired"
        return m["status"]

    def get(self, mid: str) -> dict | None:
        return self._row(mid)

    def public(self, mid: str, with_spends: bool = False) -> dict:
        m = self._row(mid)
        if not m:
            raise MandateError("unknown mandate")
        out = {"mandate_id": m["mandate_id"], "status": self._status(m), "agent_id": m["agent_id"],
               "terms": {"budget_usd": m["budget"] / 1_000_000, "max_per_job_usd": m["per_job"] / 1_000_000,
                         "backends": json.loads(m["backends"]) or "any paid backend",
                         "problems": json.loads(m["problems"]) or "any", "max_shots": m["max_shots"],
                         "expires_at": m["expires_at"], "purpose": m["purpose"]},
               "spent_usd": m["spent"] / 1_000_000, "remaining_usd": (m["budget"] - m["spent"]) / 1_000_000,
               "terms_text": m["message"], "terms_sha256": m["terms_hash"], "signed_with": "passkey, user verified" if m["activated_at"] else None,
               "needs_id_verification": self.needs_id(m), "created_at": m["created_at"], "activated_at": m["activated_at"],
               "attestation_id": m["attestation_id"], "revoked_at": m["revoked_at"], "revoked_by": m["revoked_by"],
               "revoke_reason": m["revoke_reason"], "revocation_attestation_id": m["revocation_attestation_id"]}
        if with_spends:
            out["spends"] = [{"job_id": r["job_id"], "backend": r["backend_id"], "shots": r["shots"],
                              "usd": r["amount"] / 1_000_000, "status": r["status"], "at": r["created_at"]}
                             for r in self._db.execute("SELECT * FROM qmandate_spends WHERE mandate_id=? ORDER BY created_at DESC LIMIT 200",
                                                       (mid,))]
        return out

    def for_agent(self, agent_id: str) -> list[dict]:
        rows = self._db.execute("SELECT mandate_id FROM qmandates WHERE agent_id=? ORDER BY created_at DESC LIMIT 50", (agent_id,))
        return [self.public(r["mandate_id"]) for r in rows]

    def active_count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM qmandates WHERE status='active' AND expires_at > ?", (_iso(),)).fetchone()[0]
