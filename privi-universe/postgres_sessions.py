"""Optional PostgreSQL session store for a DEDICATED, reviewed session database.

Not imported by Privi Universe's public server. Never use billing/ledger DBs.
Requires psycopg 3, a distinct Postgres database, verified TLS, schema setup
by an authorized administrator, backups, and a real configured IdP. There are
no default credentials, automatic migrations, or live writes.

This code is a prelaunch integration adapter; no production claim is made.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from contextlib import contextmanager

from browser_sessions import (
    SessionDenied, _token_hash, _safe_origin, cookie_header,
    clear_cookie_header, MAX_SESSIONS, SESSION_SECONDS,
)
from session_storage_config import check_session_storage

try:
    import psycopg
except ImportError:
    psycopg = None

# DBA-applied migration in postgres_session_schema.sql; never auto-create.
TABLE = "privi_sessions.sessions"
LOCK_ID = 7462589  # transaction-scoped advisory lock serializes issue capacity


class PostgresSessionStore:
    """Read/write session store; construction does not contact Postgres.

    DB role must have no permissions outside the privi_sessions schema.
    All queries use fixed SQL and parameterized values. Never expose DSNs
    in logs, exceptions or API responses.
    """
    def __init__(self, config, *, now=None, connector=None):
        state = check_session_storage(config)
        if not state["ready"]:
            raise SessionDenied("Dedicated session database preflight failed")
        self._dsn = config["PRIVI_UNIVERSE_SESSION_DATABASE_URL"]
        self._now = now if now is not None else time.time
        self._connector = connector if connector is not None else (
            psycopg.connect if psycopg is not None else None
        )
        if self._connector is None:
            raise SessionDenied("Postgres driver not installed")

    @contextmanager
    def _connection(self):
        try:
            connection = self._connector(self._dsn, connect_timeout=5)
        except Exception as exc:
            raise SessionDenied("Dedicated session database unavailable") from exc
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _row(cursor):
        return cursor.fetchone()

    def issue(self, *, subject, issuer, auth_time):
        if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
            raise SessionDenied("Invalid verified identity")
        if not isinstance(issuer, str) or not issuer.startswith("https://"):
            raise SessionDenied("Invalid verified issuer")
        now = int(self._now())
        if (not isinstance(auth_time, (int, float)) or isinstance(auth_time, bool)
                or auth_time < now - 300 or auth_time > now + 45):
            raise SessionDenied("Authentication is stale")
        handle, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self._connection() as db:
            # psycopg transaction context commits on success, rolls back on error.
            with db.transaction():
                with db.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
                    cur.execute(f"DELETE FROM {TABLE} WHERE expires_at <= %s", (now,))
                    cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
                    if cur.fetchone()[0] >= MAX_SESSIONS:
                        raise SessionDenied("Session capacity reached")
                    cur.execute(
                        f"INSERT INTO {TABLE} "
                        "(handle_hash, subject, issuer, authenticated_at, expires_at, csrf_hash) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (hashlib.sha256(handle.encode()).digest(), subject, issuer,
                         int(auth_time), now + SESSION_SECONDS,
                         hashlib.sha256(csrf.encode()).digest())
                    )
        return {"session_handle":handle, "csrf_token":csrf,
                "expires_in":SESSION_SECONDS, "cookie":cookie_header(handle),
                "access":"ACCOUNT_ONLY_NO_PRO"}

    def validate(self, handle):
        key = _token_hash(handle)
        with self._connection() as db:
            with db.cursor() as cur:
                cur.execute(
                    f"SELECT subject, issuer, authenticated_at, expires_at "
                    f"FROM {TABLE} WHERE handle_hash = %s", (key,)
                )
                row = self._row(cur)
        if not row or row[3] <= self._now():
            raise SessionDenied("Session invalid or expired")
        return {"subject":row[0], "issuer":row[1], "auth_time":row[2],
                "expires_at":row[3], "pro_access":False}

    def _check_csrf_locked(self, cur, handle, csrf_token, origin, expected_origin):
        key = _token_hash(handle)
        if not _safe_origin(origin, expected_origin):
            raise SessionDenied("Invalid origin")
        if not isinstance(csrf_token, str) or not 32 <= len(csrf_token) <= 128:
            raise SessionDenied("CSRF token missing")
        cur.execute(
            f"SELECT expires_at, csrf_hash FROM {TABLE} "
            "WHERE handle_hash = %s FOR UPDATE", (key,)
        )
        row = self._row(cur)
        if not row or row[0] <= self._now():
            raise SessionDenied("Session invalid or expired")
        if not hmac.compare_digest(row[1], hashlib.sha256(csrf_token.encode()).digest()):
            raise SessionDenied("CSRF token mismatch")
        return key

    def require_csrf(self, handle, *, csrf_token, origin, expected_origin):
        with self._connection() as db:
            with db.transaction():
                with db.cursor() as cur:
                    self._check_csrf_locked(
                        cur, handle, csrf_token, origin, expected_origin)
        return True

    def revoke(self, handle, *, csrf_token, origin, expected_origin):
        with self._connection() as db:
            with db.transaction():
                with db.cursor() as cur:
                    key = self._check_csrf_locked(
                        cur, handle, csrf_token, origin, expected_origin)
                    cur.execute(f"DELETE FROM {TABLE} WHERE handle_hash = %s",(key,))
                    if cur.rowcount != 1:
                        raise SessionDenied("Session already revoked")
        return clear_cookie_header()

    def revoke_subject(self, *, subject, issuer):
        """Only callable by trusted back-end handling verified IdP revocation."""
        if not isinstance(subject, str) or not subject or not isinstance(issuer, str) or not issuer:
            raise SessionDenied("Verified issuer/subject required")
        with self._connection() as db:
            with db.transaction():
                with db.cursor() as cur:
                    cur.execute(f"DELETE FROM {TABLE} WHERE subject = %s AND issuer = %s",
                                (subject,issuer))
                    return cur.rowcount
