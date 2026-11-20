"""SQLite-backed Privi Universe session-store prototype.

The database is persistent across LOCAL process restarts and supports
transactional logout/revocation. It is NOT wired to public login. Render free
ephemeral disk is not durable; production needs a managed shared database,
backup and encryption-at-rest controls, independent identity lifecycle,
user rate limits, and provider revocation/webhook verification.

No raw session handles, CSRF secrets, tokens, or provider credentials are stored.
No Pro / payment claims are ever stored or granted.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from browser_sessions import (
    COOKIE_NAME, SESSION_SECONDS, MAX_SESSIONS,
    SessionDenied, _token_hash, _safe_origin, cookie_header, clear_cookie_header,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    handle_hash BLOB PRIMARY KEY,
    subject TEXT NOT NULL,
    issuer TEXT NOT NULL,
    authenticated_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    csrf_hash BLOB NOT NULL,
    CHECK (length(handle_hash) = 32),
    CHECK (length(csrf_hash) = 32)
);
CREATE INDEX IF NOT EXISTS sessions_subject_issuer ON sessions(subject, issuer);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
"""


class SqliteSessionStore:
    """Testable transactional session implementation, NOT a distributed store.

    Each method uses a new SQLite connection for multi-process durability,
    with BEGIN IMMEDIATE for mutations and atomic revocation checks.
    Production must use a real shared database and credentialed connection.
    """
    def __init__(self, database, *, now=None):
        if not isinstance(database, (str, Path)):
            raise SessionDenied("A persistent database path is required")
        database = str(database)
        if not database or database == ":memory:" or database.startswith("file:"):
            raise SessionDenied("A file-backed database path is required")
        self.path = database
        self._now = now if now is not None else time.time
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            yield db
        finally:
            db.close()

    def issue(self, *, subject, issuer, auth_time):
        if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
            raise SessionDenied("Invalid verified subject")
        if not isinstance(issuer, str) or not issuer.startswith("https://"):
            raise SessionDenied("Invalid issuer")
        now = int(self._now())
        if (not isinstance(auth_time, (int, float)) or isinstance(auth_time, bool)
                or auth_time < now - 300 or auth_time > now + 45):
            raise SessionDenied("Stale or invalid verified authentication time")
        handle = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        key = _token_hash(handle)
        with self._lock, self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
                count = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                if count >= MAX_SESSIONS:
                    raise SessionDenied("Session capacity reached")
                db.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                    (key, subject, issuer, int(auth_time), now + SESSION_SECONDS,
                     hashlib.sha256(csrf.encode()).digest())
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return {"session_handle":handle, "csrf_token":csrf,
                "expires_in": SESSION_SECONDS, "cookie":cookie_header(handle),
                "access":"ACCOUNT_ONLY_NO_PRO"}

    def validate(self, handle):
        key = _token_hash(handle)
        with self._connect() as db:
            row = db.execute(
                "SELECT subject, issuer, authenticated_at, expires_at "
                "FROM sessions WHERE handle_hash = ?", (key,)
            ).fetchone()
        if not row or row[3] <= self._now():
            raise SessionDenied("Session absent, expired or revoked")
        return {"subject":row[0], "issuer":row[1], "auth_time":row[2],
                "expires_at":row[3], "pro_access":False}

    def _require_csrf(self, db, handle, *, csrf_token, origin, expected_origin):
        key = _token_hash(handle)
        if not _safe_origin(origin, expected_origin):
            raise SessionDenied("Invalid origin")
        if (not isinstance(csrf_token, str) or not 32 <= len(csrf_token) <= 128):
            raise SessionDenied("Missing anti-CSRF proof")
        row = db.execute(
            "SELECT expires_at, csrf_hash FROM sessions WHERE handle_hash = ?",(key,)
        ).fetchone()
        if not row or row[0] <= self._now():
            raise SessionDenied("Session expired or revoked")
        got = hashlib.sha256(csrf_token.encode()).digest()
        if not hmac.compare_digest(row[1],got):
            raise SessionDenied("Wrong anti-CSRF proof")
        return key

    def require_csrf(self, handle, *, csrf_token, origin, expected_origin):
        with self._connect() as db:
            self._require_csrf(db,handle,csrf_token=csrf_token,
                               origin=origin,expected_origin=expected_origin)
        return True

    def revoke(self, handle, *, csrf_token, origin, expected_origin):
        with self._lock, self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                key = self._require_csrf(
                    db,handle,csrf_token=csrf_token,
                    origin=origin,expected_origin=expected_origin
                )
                count = db.execute(
                    "DELETE FROM sessions WHERE handle_hash = ?",(key,)
                ).rowcount
                if count != 1:
                    raise SessionDenied("Session already revoked")
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return clear_cookie_header()

    def revoke_subject(self, *, subject, issuer):
        """Trusted server-only upstream logout; no client-provided identities."""
        if not isinstance(subject, str) or not subject or not isinstance(issuer,str) or not issuer:
            raise SessionDenied("Verified subject and issuer required")
        with self._lock, self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                count=db.execute(
                    "DELETE FROM sessions WHERE subject = ? AND issuer = ?",
                    (subject,issuer)
                ).rowcount
                db.execute("COMMIT")
                return count
            except Exception:
                db.execute("ROLLBACK")
                raise
