"""Privi ONE SQLite receipt journal regression tests, no external network."""
import importlib.util
import json
import sqlite3
import tempfile
import threading
from pathlib import Path
import unittest

PATH = Path(__file__).with_name("receipt_journal.py")
spec = importlib.util.spec_from_file_location("privi_one_journal_test", PATH)
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "receipts.sqlite3")
        self.store = journal.Journal(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_idempotency_survives_journal_reopen(self):
        calls = [0]
        def create():
            calls[0] += 1
            return {"receipt": {"mode": "SIMULATED", "n": calls[0]}}
        a, replayed = self.store.run_once(
            "anonymous-sid-1", "retry-request-001", {"budget": 10}, create, now=100)
        self.assertFalse(replayed)
        again = journal.Journal(self.path)
        b, replayed = again.run_once(
            "anonymous-sid-1", "retry-request-001", {"budget": 10}, create, now=200)
        self.assertTrue(replayed)
        self.assertEqual(a, b)
        self.assertEqual(calls[0], 1)
        self.assertTrue(again.audit()["valid"])

    def test_conflict_denied(self):
        self.store.run_once("sid", "retry-request-002", {"cost": 10},
                            lambda: {"n": 1})
        with self.assertRaises(ValueError):
            self.store.run_once("sid", "retry-request-002", {"cost": 100},
                                lambda: {"n": 2})

    def test_concurrent_retries_atomic(self):
        calls, results, lock = [0], [], threading.Lock()
        def create():
            with lock:
                calls[0] += 1
            return {"receipt": "same"}
        def worker():
            results.append(self.store.run_once(
                "session", "retry-concurrent-003", {"x": 1}, create))
        ts = [threading.Thread(target=worker) for _ in range(25)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(calls[0], 1)
        self.assertEqual(sum(replayed for _, replayed in results), 24)
        self.assertEqual(self.store.audit()["entries_checked"], 1)

    def test_chain_and_tamper_detection(self):
        for i in range(3):
            self.store.run_once("s", f"request-{i:03d}", {"i": i},
                                lambda i=i: {"receipt": {"i": i}})
        self.assertTrue(self.store.audit()["valid"])
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE receipts SET receipt_json=? WHERE seq=2",
                       (json.dumps({"receipt": {"i": 500}}),))
        self.assertFalse(self.store.audit()["valid"])

    def test_integrity_failure_rolls_back(self):
        with self.assertRaises(RuntimeError):
            self.store.run_once("s", "request-fail-004", {"i": 0},
                                lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        self.assertEqual(self.store.audit()["entries_checked"], 0)


if __name__ == "__main__":
    unittest.main()
