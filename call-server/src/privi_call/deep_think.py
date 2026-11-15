# Copyright (c) 2026 Privi World Corp. All rights reserved.
"""Privi Deep Think: consented, hash-only coding revision ledger.

Does not execute code or guarantee bug-free output. Checks are self-reported
by the calling agent; a signed x402 wallet payment is required for paid redos.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import threading
import time
from typing import Any

SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHECKS = ("syntax", "tests", "edge_cases", "security", "integration")
PRICE_USDC = "0.01"


class DeepThinkError(ValueError):
    pass


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash(value: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise DeepThinkError("source_sha256 must be a lowercase 64-character SHA-256 digest")
    return value


class DeepThinkLedger:
    """Persistent, task-token-scoped, hash-only revision ledger."""

    def __init__(self, db_path: str):
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS deep_think_tasks (
          task_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, goal_hash TEXT NOT NULL,
          language TEXT NOT NULL, current_hash TEXT, revisions INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS deep_think_redos (
          task_id TEXT NOT NULL, revision INTEGER NOT NULL,
          from_hash TEXT NOT NULL, to_hash TEXT NOT NULL, tx_hash TEXT NOT NULL UNIQUE,
          created_at INTEGER NOT NULL, PRIMARY KEY(task_id,revision));
        """)

    def start(self, goal: str, language: str, criteria: list[str]) -> dict[str, Any]:
        if not isinstance(goal, str) or not (10 <= len(goal.strip()) <= 4000):
            raise DeepThinkError("goal must be between 10 and 4000 characters")
        if not isinstance(language, str) or not (1 <= len(language.strip()) <= 40):
            raise DeepThinkError("language must be 1-40 characters")
        if (not isinstance(criteria, list) or not (1 <= len(criteria) <= 20) or
                any(not isinstance(x, str) or not (2 <= len(x.strip()) <= 300) for x in criteria)):
            raise DeepThinkError("criteria must contain 1-20 clear acceptance criteria")
        task_id, token = "dt_" + secrets.token_hex(12), "dts_" + secrets.token_urlsafe(32)
        now = int(time.time())
        with self._lock:
            self._db.execute("INSERT INTO deep_think_tasks VALUES (?,?,?,?,NULL,0,?,?)",
                             (task_id, _digest(token), _digest(goal), language.strip(), now, now))
        return {
            "task_id": task_id, "task_token": token, "revision": 0,
            "price": {"first_submission": "free", "redo": PRICE_USDC, "currency": "USDC", "network": "Base"},
            "planning_contract": [
                "Restate requested behavior, constraints, non-goals and ambiguities.",
                "Inspect actual code, dependencies, interfaces and existing tests before editing.",
                "Design a minimal change; analyze failure modes, security and concurrency.",
                "Translate every acceptance criterion into tests and edge cases.",
                "Implement the smallest coherent patch; avoid unrelated refactors.",
                "Run syntax, unit, edge-case, security and integration checks locally.",
                "Review the diff, report actual command results and never invent passing tests.",
                "Submit only the SHA-256 of the code snapshot and honestly reported checks."
            ],
            "acceptance_criteria": criteria,
            "privacy": "Goal and source are not stored; keep task_token secret. Check results are self-reported."
        }

    def _task(self, task_id: str, token: str) -> sqlite3.Row:
        if not isinstance(task_id, str) or not isinstance(token, str) or not token.startswith("dts_"):
            raise DeepThinkError("invalid task credentials")
        row = self._db.execute("SELECT * FROM deep_think_tasks WHERE task_id=? AND token_hash=?",
                               (task_id, _digest(token))).fetchone()
        if row is None:
            raise DeepThinkError("unknown task or invalid task token")
        return row

    def review(self, task_id: str, token: str, source_sha256: str,
               checks: dict[str, bool]) -> dict[str, Any]:
        source_sha256 = _hash(source_sha256)
        if not isinstance(checks, dict) or set(checks) != set(CHECKS) or any(type(v) is not bool for v in checks.values()):
            raise DeepThinkError("checks must supply syntax, tests, edge_cases, security and integration booleans")
        with self._lock:
            row = self._task(task_id, token)
            if row["current_hash"] not in (None, source_sha256):
                return {"status": "redo_requires_payment", "task_id": task_id,
                        "prior_sha256": row["current_hash"], "new_sha256": source_sha256,
                        "fee_usdc": PRICE_USDC, "next_tool": "deep_think_redo",
                        "note": "An operator-approved, settled x402 payment is required to record a changed snapshot."}
            if row["current_hash"] is None:
                self._db.execute("UPDATE deep_think_tasks SET current_hash=?,updated_at=? WHERE task_id=?",
                                 (source_sha256, int(time.time()), task_id))
            all_passed = all(checks.values())
            return {"status": "reviewed" if all_passed else "needs_improvement",
                    "task_id": task_id, "source_sha256": source_sha256,
                    "revision": row["revisions"], "self_reported_checks": checks,
                    "all_checks_reported_passed": all_passed,
                    "limits": "Checks were reported by the calling agent, not executed independently."}

    def inspect_redo(self, task_id: str, token: str, prior_sha256: str, new_sha256: str) -> dict[str, Any]:
        prior_sha256, new_sha256 = _hash(prior_sha256), _hash(new_sha256)
        with self._lock:
            row = self._task(task_id, token)
            if row["current_hash"] == new_sha256:
                return {"status": "already_recorded", "revision": row["revisions"], "charged": False}
            if row["current_hash"] != prior_sha256:
                raise DeepThinkError("stale or unknown prior snapshot; check current snapshot before payment")
            if prior_sha256 == new_sha256:
                raise DeepThinkError("identical hashes are not a redo")
            return {"status": "payment_required", "next_revision": row["revisions"] + 1,
                    "fee_usdc": PRICE_USDC, "network": "Base", "task_id": task_id}

    def record_paid_redo(self, task_id: str, token: str, prior_sha256: str,
                         new_sha256: str, tx_hash: str) -> dict[str, Any]:
        prior_sha256, new_sha256 = _hash(prior_sha256), _hash(new_sha256)
        if not isinstance(tx_hash, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash):
            raise DeepThinkError("settlement must include an EVM transaction hash")
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._task(task_id, token)
                if row["current_hash"] != prior_sha256 or prior_sha256 == new_sha256:
                    raise DeepThinkError("code snapshot changed or redo is not distinct")
                if self._db.execute("SELECT 1 FROM deep_think_redos WHERE tx_hash=?",
                                    (tx_hash.lower(),)).fetchone():
                    raise DeepThinkError("payment transaction already used")
                revision = row["revisions"] + 1
                self._db.execute("INSERT INTO deep_think_redos VALUES (?,?,?,?,?,?)",
                                 (task_id, revision, prior_sha256, new_sha256, tx_hash.lower(), int(time.time())))
                self._db.execute("UPDATE deep_think_tasks SET current_hash=?,revisions=?,updated_at=? WHERE task_id=?",
                                 (new_sha256, revision, int(time.time()), task_id))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return {"status": "recorded_paid_redo", "task_id": task_id,
                "revision": revision, "source_sha256": new_sha256,
                "usdc_fee": PRICE_USDC, "network": "Base", "settlement_tx": tx_hash}
