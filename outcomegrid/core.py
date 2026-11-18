"""Privi OutcomeGrid: offline synthetic outcome registry and reputation prototype.

No money, token, AI-provider calls, real customers or production identity.
Every trust identity is a synthetic fixture supplied to this local registry.
Only verifier roles can attest, and an executor cannot verify its own work.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import time

SCHEMA = "privi-outcomegrid-sandbox-v1"
STATES = frozenset({"accepted", "rejected"})
MAX_TEXT = 512


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def ident(s):
    return isinstance(s, str) and 1 <= len(s) <= 80 and all(
        c.isascii() and (c.isalnum() or c in "-_") for c in s)


class OutcomeGrid:
    def __init__(self, db_path):
        if not isinstance(db_path, str) or not db_path:
            raise ValueError("database path required")
        self.db_path = db_path
        self.lock = threading.RLock()
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs(
                job_id TEXT PRIMARY KEY, buyer TEXT NOT NULL,
                agent TEXT NOT NULL, verifier TEXT NOT NULL,
                criteria_json TEXT NOT NULL, criteria_hash TEXT NOT NULL,
                created INTEGER NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS outcomes(
                job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
                evidence_digest TEXT NOT NULL, decision TEXT NOT NULL,
                verified_by TEXT NOT NULL, note_hash TEXT NOT NULL,
                outcome_hash TEXT NOT NULL, recorded INTEGER NOT NULL
            )""")

    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def post_job(self, *, job_id, buyer, agent, verifier, criteria, now=None):
        if not all(map(ident, (job_id, buyer, agent, verifier))):
            raise ValueError("invalid job identity")
        if len({buyer, agent, verifier}) != 3:
            raise PermissionError("buyer, executor and verifier must differ")
        if (not isinstance(criteria, dict) or set(criteria) != {"check", "expected"}
                or not all(isinstance(v, str) and 1 <= len(v) <= MAX_TEXT
                           for v in criteria.values())):
            raise ValueError("exact, bounded acceptance criteria required")
        created = int(time.time()) if now is None else now
        if type(created) is not int or created < 0:
            raise ValueError("invalid timestamp")
        criterion_hash = digest(criteria)
        with self.lock:
            db = self._db()
            try:
                db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)",
                           (job_id, buyer, agent, verifier, canonical(criteria).decode(),
                            criterion_hash, created))
                db.commit()
            finally:
                db.close()
        return {"job_id": job_id, "criteria_sha256": criterion_hash,
                "status": "awaiting_independent_verification",
                "mode": "SYNTHETIC_NO_EXECUTION"}

    def attest(self, *, job_id, actor, decision, evidence_digest, note="", now=None):
        if not ident(job_id) or not ident(actor) or decision not in STATES:
            raise ValueError("invalid attestation")
        if (not isinstance(evidence_digest, str) or len(evidence_digest) != 64
                or any(c not in "0123456789abcdef" for c in evidence_digest)):
            raise ValueError("evidence must be a SHA-256 hexadecimal digest")
        if not isinstance(note, str) or len(note) > MAX_TEXT:
            raise ValueError("note too long")
        recorded = int(time.time()) if now is None else now
        if type(recorded) is not int or recorded < 0:
            raise ValueError("invalid timestamp")
        with self.lock:
            db = self._db()
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT buyer, agent, verifier, criteria_hash FROM jobs WHERE job_id=?",
                    (job_id,)).fetchone()
                if row is None:
                    raise ValueError("unknown job")
                buyer, agent, verifier, criteria_hash = row
                if actor != verifier or actor in (buyer, agent):
                    raise PermissionError("only a separate designated verifier may attest")
                event = {"schema": SCHEMA, "job_id": job_id, "criteria_hash": criteria_hash,
                         "agent": agent, "verifier": actor, "decision": decision,
                         "evidence_digest": evidence_digest,
                         "note_sha256": hashlib.sha256(note.encode()).hexdigest(),
                         "recorded": recorded}
                out_hash = digest(event)
                # unique job_id is enforced by SQLite; retries cannot double-credit.
                existing = db.execute(
                    "SELECT outcome_hash FROM outcomes WHERE job_id=?", (job_id,)).fetchone()
                if existing:
                    raise ValueError("job already attested; corrections need separate dispute process")
                db.execute("INSERT INTO outcomes VALUES(?,?,?,?,?,?,?)",
                           (job_id, evidence_digest, decision, actor,
                            event["note_sha256"], out_hash, recorded))
                db.commit()
                return {"outcome": event, "outcome_sha256": out_hash,
                        "mode": "SYNTHETIC_ATTESTATION_NOT_INDEPENDENT_PROOF"}
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def scoreboard(self):
        """Recompute from records; include only designated verifier attestations.

        Metric is demonstration-only acceptance percentage; never extrapolate
        1 outcome to reliable real-world performance.
        """
        with self.lock:
            db = self._db()
            try:
                rows = db.execute("""SELECT j.agent, o.decision
                    FROM outcomes o JOIN jobs j ON j.job_id=o.job_id
                    WHERE o.verified_by=j.verifier AND j.agent != j.verifier
                    AND j.buyer != j.verifier AND j.buyer != j.agent""").fetchall()
            finally:
                db.close()
        stats = {}
        for agent, decision in rows:
            slot = stats.setdefault(agent, {"agent": agent, "accepted": 0,
                                            "rejected": 0, "verified_total": 0})
            slot[decision] += 1
            slot["verified_total"] += 1
        for slot in stats.values():
            slot["acceptance_rate_percent"] = round(
                100 * slot["accepted"] / slot["verified_total"], 1)
        return {"schema": SCHEMA, "synthetic_only": True,
                "agents": sorted(stats.values(), key=lambda x: (-x["verified_total"], x["agent"]))}

    def job_status(self, job_id):
        if not ident(job_id):
            raise ValueError("invalid job")
        with self.lock:
            db = self._db()
            try:
                row = db.execute("""SELECT j.job_id, j.agent, j.criteria_hash,
                    o.decision, o.evidence_digest, o.outcome_hash
                    FROM jobs j LEFT JOIN outcomes o ON j.job_id=o.job_id
                    WHERE j.job_id=?""", (job_id,)).fetchone()
            finally:
                db.close()
        if not row:
            return None
        return {"job_id": row[0], "agent": row[1], "criteria_sha256": row[2],
                "decision": row[3], "evidence_sha256": row[4],
                "outcome_sha256": row[5], "mode": "SYNTHETIC_DEMO"}
