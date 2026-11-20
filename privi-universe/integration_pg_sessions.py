"""Real PostgreSQL 16 session integration tests (CI-only, isolated service).

Run ONLY in the dedicated GitHub Actions job using a disposable PostgreSQL
service and PG_TEST_DSN. This module intentionally does not match test_*.py
and is not run by Render's regular stdlib portal build.

The production preflight remains enforced; the test's injected connector
rewrites a synthetic, preflight-valid DSN to the isolated CI database URL.
Never pass a real Privi billing database to PG_TEST_DSN.
"""
import os
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

from postgres_sessions import PostgresSessionStore
from browser_sessions import SessionDenied

ORIGIN = "https://privi-universe-demo.onrender.com"
ISSUER = "https://id.example.test/"
CONFIG = {
    "PRIVI_UNIVERSE_SESSION_BACKEND": "postgres",
    "PRIVI_UNIVERSE_SESSION_DATABASE_URL":
        "postgresql://isolated_session_user:synthetic@session-ci.example.test/"
        "privi_universe_ci_sessions?sslmode=verify-full",
    "PRIVI_UNIVERSE_SESSION_SCHEMA": "privi_sessions",
    "PRIVI_UNIVERSE_SESSION_ADMIN_REVIEWED": "true",
    "PRIVI_UNIVERSE_SESSION_BACKUPS_VERIFIED": "true",
}


def ci_connection_string():
    url = os.environ.get("PG_TEST_DSN", "")
    parsed = urlsplit(url)
    # CI-only localhost connection is deliberately isolated from all
    # connected Render instances and explicitly named as disposable.
    if (parsed.scheme not in ("postgresql", "postgres") or
            parsed.hostname not in ("localhost", "127.0.0.1") or
            parsed.path != "/privi_universe_ci_sessions"):
        raise RuntimeError("PG_TEST_DSN must point to disposable localhost CI database")
    return url


class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = ci_connection_string()
        cls.now = int(time.time())
        with psycopg.connect(cls.dsn) as db:
            # CI runner owns the temporary database. Migration is executed
            # here only after checking fixed localhost + database name.
            sql = Path(__file__).with_name("postgres_session_schema.sql").read_text()
            db.execute(sql)
        cls.connector = lambda ignored, **kwargs: psycopg.connect(cls.dsn, **kwargs)

    def setUp(self):
        with psycopg.connect(self.dsn) as db:
            db.execute("TRUNCATE TABLE privi_sessions.sessions")
        self.store = PostgresSessionStore(
            CONFIG, now=lambda: self.now, connector=self.connector)

    def issue(self, subject="alice"):
        return self.store.issue(
            subject=subject, issuer=ISSUER, auth_time=self.now)

    def test_issue_validate_and_no_paid_access(self):
        session = self.issue()
        check = self.store.validate(session["session_handle"])
        self.assertEqual(check["subject"], "alice")
        self.assertFalse(check["pro_access"])
        self.assertEqual(session["access"], "ACCOUNT_ONLY_NO_PRO")
        with psycopg.connect(self.dsn) as db:
            row = db.execute("SELECT handle_hash, csrf_hash, subject "
                             "FROM privi_sessions.sessions").fetchone()
        self.assertEqual(len(row[0]), 32)
        self.assertEqual(len(row[1]), 32)
        self.assertNotEqual(row[0], session["session_handle"].encode())
        self.assertNotEqual(row[1], session["csrf_token"].encode())

    def test_csrf_logout_and_cross_connection_revocation(self):
        session = self.issue()
        separate = PostgresSessionStore(
            CONFIG, now=lambda: self.now, connector=self.connector)
        with self.assertRaises(SessionDenied):
            separate.revoke(
                session["session_handle"], csrf_token=session["csrf_token"],
                origin="https://attacker.test", expected_origin=ORIGIN)
        self.assertTrue(self.store.validate(session["session_handle"]))
        self.assertTrue(separate.require_csrf(
            session["session_handle"], csrf_token=session["csrf_token"],
            origin=ORIGIN, expected_origin=ORIGIN))
        cleared = separate.revoke(
            session["session_handle"], csrf_token=session["csrf_token"],
            origin=ORIGIN, expected_origin=ORIGIN)
        self.assertIn("Max-Age=0", cleared)
        with self.assertRaises(SessionDenied):
            self.store.validate(session["session_handle"])

    def test_subject_scoped_revocation(self):
        a, b, other = self.issue(), self.issue(), self.issue(subject="bob")
        second = PostgresSessionStore(
            CONFIG, now=lambda: self.now, connector=self.connector)
        self.assertEqual(second.revoke_subject(subject="alice", issuer=ISSUER), 2)
        for session in (a, b):
            with self.assertRaises(SessionDenied):
                self.store.validate(session["session_handle"])
        self.assertEqual(self.store.validate(other["session_handle"])["subject"], "bob")

    def test_expiration_rejected(self):
        session = self.issue()
        self.now += 1800
        with self.assertRaises(SessionDenied):
            self.store.validate(session["session_handle"])

    def test_concurrent_logout_single_winner(self):
        session = self.issue()
        results = []
        lock = threading.Lock()
        def logout():
            separate = PostgresSessionStore(
                CONFIG, now=lambda: self.now, connector=self.connector)
            try:
                separate.revoke(session["session_handle"],
                                csrf_token=session["csrf_token"],
                                origin=ORIGIN, expected_origin=ORIGIN)
                result = True
            except SessionDenied:
                result = False
            with lock:
                results.append(result)
        jobs = [threading.Thread(target=logout) for _ in range(5)]
        for job in jobs: job.start()
        for job in jobs: job.join()
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 4)

    def test_session_capacity_fails_closed(self):
        # Use direct fixture inserts to avoid opening 200 network sessions.
        now = self.now
        with psycopg.connect(self.dsn) as db:
            db.executemany(
                "INSERT INTO privi_sessions.sessions "
                "(handle_hash,subject,issuer,authenticated_at,expires_at,csrf_hash) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                [(i.to_bytes(32, "big"), "fixture", ISSUER, now, now+300,
                  (i+1).to_bytes(32,"big")) for i in range(200)]
            )
        with self.assertRaises(SessionDenied):
            self.issue()


if __name__ == "__main__":
    unittest.main()
