"""Anonymous sandbox identity and retry-safety tests."""
import importlib.util
import json
import threading
from pathlib import Path
import unittest

PATH = Path(__file__).with_name("sandbox_identity.py")
spec = importlib.util.spec_from_file_location("sandbox_identity_under_test", PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
KEY = b"local-test-key-for-synthetic-sandbox-only-32"


class SandboxTests(unittest.TestCase):
    def test_session_expiration_and_tamper(self):
        mgr = mod.SandboxIdentity(KEY)
        issued = mgr.issue(now=100)
        self.assertIsNotNone(mgr.verify(issued["token"], now=105))
        self.assertIsNone(mgr.verify(issued["token"], now=100 + mod.TTL_SECONDS + 1))
        altered = issued["token"][:-1] + ("A" if issued["token"][-1] != "A" else "B")
        self.assertIsNone(mgr.verify(altered, now=105))
        self.assertIsNone(mod.SandboxIdentity(b"another-synthetic-identity-secret-321").verify(
            issued["token"], now=105))

    def test_concurrent_retries_return_same_result(self):
        store = mod.RetryStore()
        count = [0]
        lock = threading.Lock()
        out = []
        def create():
            with lock:
                count[0] += 1
            return {"receipt": "synthetic"}
        def call():
            out.append(store.run_once("session", "same-request-1234",
                                      {"budget": 10}, create, now=100))
        ts = [threading.Thread(target=call) for _ in range(20)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(count[0], 1)
        self.assertEqual(sum(replay for _, replay in out), 19)
        self.assertEqual(len({id(result) for result, _ in out}), 1)

    def test_conflicting_replay_refused(self):
        store = mod.RetryStore()
        store.run_once("s", "request-id-111", {"budget": 1}, lambda: {"ok": True}, now=0)
        with self.assertRaises(ValueError):
            store.run_once("s", "request-id-111", {"budget": 2}, lambda: {"ok": True}, now=1)

    def test_separate_sessions_and_expiry(self):
        store = mod.RetryStore(max_entries=2)
        a, _ = store.run_once("a", "request-id-111", {"x": 1}, lambda: {"n": 1}, now=0)
        b, replay = store.run_once("b", "request-id-111", {"x": 1}, lambda: {"n": 2}, now=1)
        self.assertFalse(replay)
        self.assertNotEqual(a, b)
        new, replay = store.run_once("a", "request-id-111", {"x": 1},
                                     lambda: {"n": 3}, now=mod.TTL_SECONDS + 2)
        self.assertFalse(replay)
        self.assertEqual(new["n"], 3)


if __name__ == "__main__":
    unittest.main()
