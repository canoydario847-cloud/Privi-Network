"""Offline Postgres adapter contract tests; never connect to real databases."""
import importlib.util
import hashlib
from pathlib import Path
import unittest
from contextlib import contextmanager

spec=importlib.util.spec_from_file_location(
    "privi_universe_pg_sessions",Path(__file__).with_name("postgres_sessions.py"))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

CONFIG={
  "PRIVI_UNIVERSE_SESSION_BACKEND":"postgres",
  "PRIVI_UNIVERSE_SESSION_DATABASE_URL":"postgresql://session_user:synthetic@id-db.example.test/universe_sessions?sslmode=verify-full",
  "PRIVI_UNIVERSE_SESSION_SCHEMA":"privi_sessions",
  "PRIVI_UNIVERSE_SESSION_ADMIN_REVIEWED":"true",
  "PRIVI_UNIVERSE_SESSION_BACKUPS_VERIFIED":"true",
}
ORIGIN="https://privi-universe-demo.onrender.com"
ISSUER="https://id.example.test/"


class FakeDb:
    """Records SQL without network/database access."""
    def __init__(self, rows=None, rowcount=1):
        self.queries=[]
        self.rows=list(rows or [])
        self.rowcount=rowcount
        self.closed=False
        self.commits=0
        self.rollbacks=0
    def close(self):
        self.closed=True
    @contextmanager
    def transaction(self):
        try:
            yield self
            self.commits+=1
        except Exception:
            self.rollbacks+=1
            raise
    @contextmanager
    def cursor(self):
        yield self
    def execute(self, query, params=None):
        self.queries.append((query,params))
    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class PgAdapterTests(unittest.TestCase):
    def setUp(self):
        self.clock=[1000]
        self.db=FakeDb()
        self.connections=[]
        def connector(dsn, **kwargs):
            self.connections.append((dsn,kwargs))
            return self.db
        self.store=m.PostgresSessionStore(CONFIG,now=lambda:self.clock[0],
                                          connector=connector)
    def test_preflight_blocks_billing_database_and_no_connect(self):
        bad=dict(CONFIG,PRIVI_UNIVERSE_SESSION_DATABASE_URL=
                 "postgresql://u:pw@db.test/privi_billing_production?sslmode=verify-full")
        with self.assertRaises(m.SessionDenied):
            m.PostgresSessionStore(bad, connector=lambda *a,**kw:self.fail("connected"))
    def test_issue_account_only_in_transaction(self):
        self.db.rows=[(0,)]
        issued=self.store.issue(subject="alice",issuer=ISSUER,auth_time=1000)
        self.assertEqual(self.db.commits,1)
        self.assertEqual(self.db.rollbacks,0)
        self.assertTrue(self.db.closed)
        self.assertIn("HttpOnly; Secure; SameSite=Lax",issued["cookie"])
        self.assertEqual(issued["access"],"ACCOUNT_ONLY_NO_PRO")
        self.assertEqual(len(self.db.queries),4)
        self.assertIn("pg_advisory_xact_lock",self.db.queries[0][0])
        statement,params=self.db.queries[-1]
        self.assertIn("privi_sessions.sessions",statement)
        self.assertIn("%s",statement)
        self.assertEqual(len(params[0]),32)
        self.assertEqual(len(params[-1]),32)
        self.assertNotEqual(params[0],issued["session_handle"].encode())
        self.assertNotEqual(params[-1],issued["csrf_token"].encode())
    def test_capacity_rolls_back_and_rejects(self):
        self.db.rows=[(m.MAX_SESSIONS,)]
        with self.assertRaises(m.SessionDenied):
            self.store.issue(subject="alice",issuer=ISSUER,auth_time=1000)
        self.assertEqual(self.db.rollbacks,1)
        self.assertEqual(self.db.commits,0)
    def test_expired_session_does_not_validate(self):
        self.db.rows=[("alice",ISSUER,995,1000)]
        with self.assertRaises(m.SessionDenied):
            self.store.validate("x"*43)
        self.assertTrue(self.db.closed)
    def test_validate_grants_no_pro(self):
        self.db.rows=[("alice",ISSUER,995,1300)]
        result=self.store.validate("x"*43)
        self.assertFalse(result["pro_access"])
        self.assertEqual(result["subject"],"alice")
    def test_logout_uses_row_lock_and_csrf(self):
        handle="x"*43
        csrf="y"*43
        self.db.rows=[(1300,hashlib.sha256(csrf.encode()).digest())]
        header=self.store.revoke(handle,csrf_token=csrf,origin=ORIGIN,expected_origin=ORIGIN)
        self.assertIn("Max-Age=0",header)
        self.assertEqual(self.db.commits,1)
        self.assertIn("FOR UPDATE",self.db.queries[0][0])
        self.assertIn("DELETE FROM privi_sessions.sessions",self.db.queries[1][0])
        self.assertEqual(self.db.queries[1][1][0],hashlib.sha256(handle.encode()).digest())
    def test_csrf_wrong_origin_rejects_before_delete(self):
        with self.assertRaises(m.SessionDenied):
            self.store.revoke("x"*43,csrf_token="y"*43,
                              origin="https://evil.test",expected_origin=ORIGIN)
        self.assertEqual(self.db.rollbacks,1)
        self.assertEqual(self.db.queries,[])
    def test_revoke_subject_is_scoped(self):
        count=self.store.revoke_subject(subject="alice",issuer=ISSUER)
        self.assertEqual(count,1)
        query,params=self.db.queries[0]
        self.assertIn("subject = %s AND issuer = %s",query)
        self.assertEqual(params,("alice",ISSUER))
    def test_database_connection_error_redacted(self):
        def fail(dsn,**kwargs):
            raise RuntimeError("synthetic-secret-not-for-logs")
        store=m.PostgresSessionStore(CONFIG,connector=fail)
        with self.assertRaises(m.SessionDenied) as ctx:
            store.validate("x"*43)
        self.assertNotIn("synthetic-secret",str(ctx.exception))
    def test_db_driver_absence_fails_closed(self):
        orig=m.psycopg
        try:
            m.psycopg=None
            with self.assertRaises(m.SessionDenied):
                m.PostgresSessionStore(CONFIG)
        finally:
            m.psycopg=orig


if __name__=="__main__":
    unittest.main()
