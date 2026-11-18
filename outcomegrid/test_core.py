"""Privi OutcomeGrid sandbox tests: independently assigned verifier and no self-credit."""
import importlib.util
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

spec = importlib.util.spec_from_file_location("outcomegrid_core", Path(__file__).with_name("core.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
EVIDENCE = hashlib.sha256(b"synthetic git test report").hexdigest()
CRITERIA = {"check": "CI result and human review", "expected": "tests_pass_and_approved"}


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = str(Path(self.dir.name) / "outcomes.sqlite")
        self.grid = mod.OutcomeGrid(self.db)

    def tearDown(self):
        self.dir.cleanup()

    def job(self, job_id="task-001", agent="agent-a"):
        return self.grid.post_job(
            job_id=job_id, buyer="buyer-org", agent=agent,
            verifier="auditor-a", criteria=CRITERIA, now=1000)

    def test_acceptance_and_score(self):
        self.job()
        result = self.grid.attest(job_id="task-001", actor="auditor-a",
                                  decision="accepted", evidence_digest=EVIDENCE, now=1001)
        self.assertEqual(result["outcome"]["decision"], "accepted")
        self.assertEqual(self.grid.scoreboard()["agents"][0]["acceptance_rate_percent"], 100)
        self.assertEqual(self.grid.job_status("task-001")["evidence_sha256"], EVIDENCE)

    def test_executor_cannot_claim_its_own_success(self):
        self.job()
        for actor in ("agent-a", "buyer-org", "random-verifier"):
            with self.assertRaises(PermissionError):
                self.grid.attest(job_id="task-001", actor=actor,
                                 decision="accepted", evidence_digest=EVIDENCE)
        self.assertEqual(self.grid.scoreboard()["agents"], [])

    def test_separation_at_job_creation(self):
        with self.assertRaises(PermissionError):
            self.grid.post_job(job_id="task-002", buyer="same", agent="same",
                               verifier="auditor", criteria=CRITERIA)
        with self.assertRaises(PermissionError):
            self.grid.post_job(job_id="task-002", buyer="buyer", agent="executor",
                               verifier="executor", criteria=CRITERIA)

    def test_duplicate_attestation_fail_closed(self):
        self.job()
        self.grid.attest(job_id="task-001", actor="auditor-a",
                         decision="accepted", evidence_digest=EVIDENCE)
        with self.assertRaises(ValueError):
            self.grid.attest(job_id="task-001", actor="auditor-a",
                             decision="accepted", evidence_digest=EVIDENCE)
        self.assertEqual(self.grid.scoreboard()["agents"][0]["verified_total"], 1)

    def test_rejection_counts_and_no_unverified_success(self):
        self.job()
        self.job(job_id="task-002")
        self.grid.attest(job_id="task-001", actor="auditor-a",
                         decision="rejected", evidence_digest=EVIDENCE)
        result = self.grid.scoreboard()["agents"][0]
        self.assertEqual(result["accepted"], 0)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["acceptance_rate_percent"], 0.0)
        self.assertIsNone(self.grid.job_status("task-002")["decision"])

    def test_bad_evidence_and_duplicate_job(self):
        self.job()
        with self.assertRaises(ValueError):
            self.grid.attest(job_id="task-001", actor="auditor-a",
                             decision="accepted", evidence_digest="not-a-hash")
        with self.assertRaises(sqlite3.IntegrityError):
            self.job()

    def test_concurrent_attestation_single_credit(self):
        self.job()
        results = []
        lock = threading.Lock()
        def attempt():
            try:
                self.grid.attest(job_id="task-001", actor="auditor-a",
                                 decision="accepted", evidence_digest=EVIDENCE)
                status = "ok"
            except ValueError:
                status = "duplicate"
            with lock:
                results.append(status)
        workers = [threading.Thread(target=attempt) for _ in range(20)]
        for t in workers: t.start()
        for t in workers: t.join()
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("duplicate"), 19)


if __name__ == "__main__":
    unittest.main()
