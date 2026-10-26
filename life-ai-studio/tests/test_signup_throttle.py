"""Regression tests for the persistent non-staging signup-abuse throttle.

All tests use an isolated temporary SQLite database and fake identities.
No production accounts, wallets, or payments are touched.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

class SignupThrottleTests(unittest.TestCase):
    def setUp(self):
        import store
        self.store = store
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_db = self.store.DB
        self.store.DB = str(Path(self.tempdir.name) / "signup.sqlite3")
        self.store.init()

    def tearDown(self):
        self.store.DB = self.previous_db
        self.tempdir.cleanup()

    def test_persists_limit_and_resets_after_window(self):
        with patch.object(self.store, "now", return_value=100000):
            for _ in range(self.store.SIGNUP_MAX_ATTEMPTS):
                self.assertTrue(self.store.signup_allowed("198.51.100.8"))
            self.assertFalse(self.store.signup_allowed("198.51.100.8"))
            self.assertFalse(self.store.signup_allowed("198.51.100.8"))
            with self.store.transaction() as db:
                row = db.execute(
                    "SELECT failures,blocked_until FROM login_throttle WHERE key_hash=?",
                    (self.store.sha("life-signup-v1:198.51.100.8"),)
                ).fetchone()
            self.assertEqual(row["failures"], self.store.SIGNUP_MAX_ATTEMPTS + 1)
            self.assertEqual(row["blocked_until"], 100000 + self.store.SIGNUP_WINDOW_SECONDS)
        with patch.object(self.store, "now", return_value=100000 + self.store.SIGNUP_WINDOW_SECONDS + 1):
            self.assertTrue(self.store.signup_allowed("198.51.100.8"))

    def test_independent_peer_limits_and_no_raw_address_stored(self):
        with patch.object(self.store, "now", return_value=100000):
            for _ in range(self.store.SIGNUP_MAX_ATTEMPTS + 1):
                self.store.signup_allowed("203.0.113.1")
            self.assertTrue(self.store.signup_allowed("203.0.113.2"))
        with self.store.transaction() as db:
            keys = [row["key_hash"] for row in db.execute("SELECT key_hash FROM login_throttle")]
        self.assertEqual(len(keys), 2)
        self.assertTrue(all(len(key) == 64 for key in keys))
        self.assertFalse(any("203.0.113" in key for key in keys))

    def test_signup_throttle_is_not_reset_by_login_success(self):
        with patch.object(self.store, "now", return_value=100000):
            for _ in range(self.store.SIGNUP_MAX_ATTEMPTS + 1):
                self.store.signup_allowed("192.0.2.2")
            self.store.login_failed("someone@example.invalid", "192.0.2.2")
            self.store.login_succeeded("someone@example.invalid", "192.0.2.2")
            self.assertFalse(self.store.signup_allowed("192.0.2.2"))

    def test_route_blocks_signup_before_creating_account(self):
        import app as life_app
        with patch.object(life_app, "STAGING_MODE", False), \
             patch.object(self.store, "signup_allowed", return_value=False) as guard:
            client = TestClient(life_app.app)
            result = client.post("/api/auth/signup", json={
                "email": "fake@example.invalid", "password": "only-for-synthetic-tests-123"
            })
        self.assertEqual(result.status_code, 429)
        guard.assert_called_once()
        with self.store.transaction() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_staging_remains_disabled_without_using_throttle(self):
        import app as life_app
        with patch.object(life_app, "STAGING_MODE", True), \
             patch.object(self.store, "signup_allowed", side_effect=AssertionError("not reached")):
            client = TestClient(life_app.app)
            result = client.post("/api/auth/signup", json={
                "email": "fake@example.invalid", "password": "only-for-synthetic-tests-123"
            })
        self.assertEqual(result.status_code, 403)


if __name__ == "__main__":
    unittest.main()
