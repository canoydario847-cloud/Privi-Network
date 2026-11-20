"""SQLite prototype session store integration and durability tests."""
import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("privi_universe_sqlite_sessions",
                                             Path(__file__).with_name("sqlite_sessions.py"))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ORIGIN="https://privi-universe-demo.onrender.com"
ISSUER="https://id.example.test/"


class SqliteSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/"sessions.db")
        self.clock=[1000]
        self.store=m.SqliteSessionStore(self.path,now=lambda:self.clock[0])
    def issue(self, store=None, user="user-1"):
        return (store or self.store).issue(subject=user,issuer=ISSUER,auth_time=self.clock[0])
    def test_sessions_persist_after_new_store_instance(self):
        issued=self.issue()
        another=m.SqliteSessionStore(self.path,now=lambda:self.clock[0])
        row=another.validate(issued["session_handle"])
        self.assertEqual(row["subject"],"user-1")
        self.assertFalse(row["pro_access"])
        self.assertIn("HttpOnly; Secure; SameSite=Lax",issued["cookie"])
        self.assertNotIn("Domain=",issued["cookie"])
        self.assertEqual(issued["access"],"ACCOUNT_ONLY_NO_PRO")
    def test_logout_revoke_propagates_between_store_instances(self):
        issued=self.issue()
        other=m.SqliteSessionStore(self.path,now=lambda:self.clock[0])
        cleared=other.revoke(issued["session_handle"],csrf_token=issued["csrf_token"],
                             origin=ORIGIN,expected_origin=ORIGIN)
        self.assertIn("Max-Age=0",cleared)
        with self.assertRaises(m.SessionDenied):
            self.store.validate(issued["session_handle"])
        with self.assertRaises(m.SessionDenied):
            other.revoke(issued["session_handle"],csrf_token=issued["csrf_token"],
                         origin=ORIGIN,expected_origin=ORIGIN)
    def test_reject_csrf_and_cross_site_without_deleting(self):
        issued=self.issue()
        for token,origin in (("x"*43,ORIGIN),(issued["csrf_token"],"https://evil.example"),
                             (issued["csrf_token"],"http://privi-universe-demo.onrender.com")):
            with self.assertRaises(m.SessionDenied):
                self.store.revoke(issued["session_handle"],csrf_token=token,
                                  origin=origin,expected_origin=ORIGIN)
        self.assertEqual(self.store.validate(issued["session_handle"])["subject"],"user-1")
    def test_expiry_and_capacity_cleanup(self):
        a=self.issue()
        self.clock[0]+=m.SESSION_SECONDS
        with self.assertRaises(m.SessionDenied):
            self.store.validate(a["session_handle"])
        b=self.issue()
        self.assertEqual(self.store.validate(b["session_handle"])["subject"],"user-1")
    def test_logout_subject_global_revocation(self):
        a=self.issue()
        b=self.issue()
        c=self.issue(user="user-2")
        another=m.SqliteSessionStore(self.path,now=lambda:self.clock[0])
        self.assertEqual(another.revoke_subject(subject="user-1",issuer=ISSUER),2)
        for issued in (a,b):
            with self.assertRaises(m.SessionDenied):
                self.store.validate(issued["session_handle"])
        self.assertEqual(self.store.validate(c["session_handle"])["subject"],"user-2")
    def test_concurrent_revoke_one_winner(self):
        a=self.issue()
        others=[m.SqliteSessionStore(self.path,now=lambda:self.clock[0]) for _ in range(6)]
        outcomes=[]
        lock=threading.Lock()
        def run(store):
            try:
                store.revoke(a["session_handle"],csrf_token=a["csrf_token"],
                             origin=ORIGIN,expected_origin=ORIGIN)
                value=True
            except m.SessionDenied:
                value=False
            with lock:outcomes.append(value)
        jobs=[threading.Thread(target=run,args=(store,)) for store in others]
        for j in jobs:j.start()
        for j in jobs:j.join()
        self.assertEqual(outcomes.count(True),1)
        self.assertEqual(outcomes.count(False),5)
    def test_never_store_raw_handles(self):
        a=self.issue()
        with self.store._connect() as db:
            stored=db.execute("SELECT handle_hash, csrf_hash FROM sessions").fetchone()
        self.assertEqual(len(stored[0]),32)
        self.assertEqual(len(stored[1]),32)
        self.assertNotEqual(stored[0],a["session_handle"].encode())
        self.assertNotEqual(stored[1],a["csrf_token"].encode())
    def test_reject_memory_db_and_wrong_auth_time(self):
        with self.assertRaises(m.SessionDenied):
            m.SqliteSessionStore(":memory:")
        with self.assertRaises(m.SessionDenied):
            self.store.issue(subject="x",issuer=ISSUER,auth_time=100)
        with self.assertRaises(m.SessionDenied):
            self.store.issue(subject="x",issuer=ISSUER,auth_time=2000)


if __name__=="__main__":
    unittest.main()
