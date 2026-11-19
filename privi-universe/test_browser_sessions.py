"""Offline session-security tests; no logins, user accounts or payments."""
import importlib.util
from pathlib import Path
import threading
import unittest

spec=importlib.util.spec_from_file_location("privi_universe_browser_sessions",Path(__file__).with_name("browser_sessions.py"))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ORIGIN="https://privi-universe-demo.onrender.com"
ISSUER="https://id.example.test/"

class SessionSecurityTests(unittest.TestCase):
    def setUp(self):
        self.clock=[1000]
        self.sessions=m.SessionStore(now=lambda:self.clock[0])
    def issue(self, subject="user-1"):
        return self.sessions.issue(subject=subject,issuer=ISSUER,auth_time=self.clock[0])
    def csrf(self, issued, *, token=None, origin=ORIGIN):
        return self.sessions.require_csrf(issued["session_handle"],csrf_token=issued["csrf_token"] if token is None else token,origin=origin,expected_origin=ORIGIN)
    def test_issue_opaque_cookie_and_account_only(self):
        issued=self.issue()
        self.assertIn("HttpOnly; Secure; SameSite=Lax",issued["cookie"])
        self.assertIn("Path=/",issued["cookie"])
        self.assertNotIn("Domain=",issued["cookie"])
        self.assertEqual(m.extract_cookie(issued["cookie"]),issued["session_handle"])
        self.assertEqual(self.sessions.validate(issued["session_handle"])["subject"],"user-1")
        self.assertFalse(self.sessions.validate(issued["session_handle"])["pro_access"])
        self.assertEqual(issued["access"],"ACCOUNT_ONLY_NO_PRO")
    def test_expiration_fails_closed(self):
        issued=self.issue()
        self.clock[0]+=m.SESSION_SECONDS
        with self.assertRaises(m.SessionDenied):
            self.sessions.validate(issued["session_handle"])
    def test_logout_revokes_and_expires_cookie(self):
        issued=self.issue()
        self.assertTrue(self.csrf(issued))
        clear=self.sessions.revoke(issued["session_handle"],csrf_token=issued["csrf_token"],origin=ORIGIN,expected_origin=ORIGIN)
        self.assertIn("Max-Age=0",clear)
        with self.assertRaises(m.SessionDenied):
            self.sessions.validate(issued["session_handle"])
        with self.assertRaises(m.SessionDenied):
            self.sessions.revoke(issued["session_handle"],csrf_token=issued["csrf_token"],origin=ORIGIN,expected_origin=ORIGIN)
    def test_csrf_mismatch_origin_and_missing_denied(self):
        issued=self.issue()
        for token,origin in [(None,"https://evil.example"),("attacker-token",ORIGIN),
                             (issued["csrf_token"],"http://privi-universe-demo.onrender.com"),
                             (issued["csrf_token"],"https://privi-universe-demo.onrender.com.evil.test")]:
            with self.assertRaises(m.SessionDenied):
                self.csrf(issued,token=token,origin=origin)
        self.assertEqual(self.sessions.validate(issued["session_handle"])["subject"],"user-1")
    def test_duplicated_cookie_and_invalid_handle_denied(self):
        issued=self.issue()
        token=issued["session_handle"]
        with self.assertRaises(m.SessionDenied):
            m.extract_cookie(f"{m.COOKIE_NAME}={token}; {m.COOKIE_NAME}={token}")
        for bad in ("", "x", "abc\nfoo", "0"*500):
            with self.assertRaises(m.SessionDenied):
                self.sessions.validate(bad)
    def test_upstream_subject_revoke(self):
        one=self.issue()
        two=self.issue()
        other=self.issue(subject="user-2")
        self.assertEqual(self.sessions.revoke_subject(subject="user-1",issuer=ISSUER),2)
        for issued in (one,two):
            with self.assertRaises(m.SessionDenied):
                self.sessions.validate(issued["session_handle"])
        self.assertEqual(self.sessions.validate(other["session_handle"])["subject"],"user-2")
    def test_replay_logout_concurrent_single_winner(self):
        issued=self.issue()
        result=[]
        lock=threading.Lock()
        def revoke():
            try:
                self.sessions.revoke(issued["session_handle"],csrf_token=issued["csrf_token"],origin=ORIGIN,expected_origin=ORIGIN)
                ok=True
            except m.SessionDenied:
                ok=False
            with lock: result.append(ok)
        threads=[threading.Thread(target=revoke) for _ in range(12)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(result.count(True),1)
        self.assertEqual(result.count(False),11)
    def test_limits_and_no_browser_issuer(self):
        with self.assertRaises(m.SessionDenied):
            self.sessions.issue(subject="x",issuer="http://bad.test",auth_time=self.clock[0])
        with self.assertRaises(m.SessionDenied):
            self.sessions.issue(subject="x",issuer=ISSUER,auth_time=self.clock[0]-301)
        for i in range(m.MAX_SESSIONS): self.issue(subject=f"demo-{i}")
        with self.assertRaises(m.SessionDenied): self.issue()
        self.clock[0]+=m.SESSION_SECONDS+1
        self.issue()

if __name__=="__main__":
    unittest.main()
