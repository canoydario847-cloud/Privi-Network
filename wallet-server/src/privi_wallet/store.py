"""SQLite storage: accounts, sessions, wallets, sends and a hash-linked activity record per account."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS wallets (
    address TEXT PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL,
    sealed_key TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sends (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, address TEXT NOT NULL, asset TEXT NOT NULL,
    amount TEXT NOT NULL, to_address TEXT NOT NULL, tx_hash TEXT, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL,
    detail TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS activity_user ON activity(user_id, id);
CREATE INDEX IF NOT EXISTS sends_user ON sends(user_id, at);
"""

GENESIS = "0" * 128
SESSION_SECONDS = 7 * 24 * 3600


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def activity_hash(prev: str, at: str, kind: str, detail: dict) -> str:
    body = json.dumps({"prev": prev, "at": at, "kind": kind, "detail": detail}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha3_512(body.encode()).hexdigest()


class Store:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    # ---------------- accounts and sessions
    def create_user(self, email: str, password_hash: str) -> int | None:
        with self._lock:
            try:
                cur = self._db.execute("INSERT INTO users(email, password, created_at) VALUES (?,?,?)",
                                       (email, password_hash, _iso()))
            except sqlite3.IntegrityError:
                return None
            return cur.lastrowid

    def user_by_email(self, email: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

    def user(self, user_id: int) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def add_session(self, token_hash: str, user_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            self._db.execute("INSERT INTO sessions VALUES (?,?,?)", (token_hash, user_id, time.time() + SESSION_SECONDS))

    def session_user(self, token_hash: str) -> int | None:
        r = self._db.execute("SELECT user_id FROM sessions WHERE token_hash=? AND expires > ?",
                             (token_hash, time.time())).fetchone()
        return r["user_id"] if r else None

    def drop_session(self, token_hash: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    # ---------------- wallets
    def add_wallet(self, user_id: int, address: str, kind: str, label: str, sealed_key: str | None) -> bool:
        with self._lock:
            try:
                self._db.execute("INSERT INTO wallets VALUES (?,?,?,?,?,?)",
                                 (address.lower(), user_id, kind, label, sealed_key, _iso()))
            except sqlite3.IntegrityError:
                return False
            return True

    def wallets(self, user_id: int) -> list[sqlite3.Row]:
        return self._db.execute("SELECT * FROM wallets WHERE user_id=? ORDER BY created_at", (user_id,)).fetchall()

    def wallet(self, user_id: int, address: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM wallets WHERE user_id=? AND address=?",
                                (user_id, address.lower())).fetchone()

    # ---------------- sends and limits
    def sent_last_24h(self, user_id: int, asset: str) -> Decimal:
        rows = self._db.execute("SELECT amount FROM sends WHERE user_id=? AND asset=? AND at > ?",
                                (user_id, asset, time.time() - 86400)).fetchall()
        return sum((Decimal(r["amount"]) for r in rows), Decimal(0))

    def record_send(self, user_id: int, address: str, asset: str, amount: Decimal, to: str) -> int:
        with self._lock:
            return self._db.execute(
                "INSERT INTO sends(user_id, address, asset, amount, to_address, at) VALUES (?,?,?,?,?,?)",
                (user_id, address.lower(), asset, str(amount), to.lower(), time.time())).lastrowid

    def set_send_tx(self, send_id: int, tx_hash: str | None) -> None:
        with self._lock:
            if tx_hash:
                self._db.execute("UPDATE sends SET tx_hash=? WHERE id=?", (tx_hash, send_id))
            else:   # broadcast failed: the amount does not count against the limit
                self._db.execute("DELETE FROM sends WHERE id=?", (send_id,))

    # ---------------- activity record (hash-linked, SHA3-512)
    def log(self, user_id: int, kind: str, detail: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            last = self._db.execute("SELECT hash FROM activity WHERE user_id=? ORDER BY id DESC LIMIT 1",
                                    (user_id,)).fetchone()
            prev = last["hash"] if last else GENESIS
            at = _iso()
            h = activity_hash(prev, at, kind, detail)
            self._db.execute("INSERT INTO activity(user_id, at, kind, detail, prev_hash, hash) VALUES (?,?,?,?,?,?)",
                             (user_id, at, kind, json.dumps(detail, sort_keys=True), prev, h))
            return {"at": at, "kind": kind, "detail": detail, "prev_hash": prev, "hash": h}

    def activity(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM activity WHERE user_id=? ORDER BY id DESC LIMIT ?",
                                (user_id, limit)).fetchall()
        return [{"at": r["at"], "kind": r["kind"], "detail": json.loads(r["detail"]),
                 "prev_hash": r["prev_hash"], "hash": r["hash"]} for r in rows]

    def verify_activity(self, user_id: int) -> dict[str, Any]:
        prev, n = GENESIS, 0
        for r in self._db.execute("SELECT * FROM activity WHERE user_id=? ORDER BY id", (user_id,)):
            if r["prev_hash"] != prev or activity_hash(prev, r["at"], r["kind"], json.loads(r["detail"])) != r["hash"]:
                return {"valid": False, "entries": n, "broken_at": n}
            prev, n = r["hash"], n + 1
        return {"valid": True, "entries": n, "head": prev}
