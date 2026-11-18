"""GitHub evidence adapter: fail closed on mismatched or incomplete check runs."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("outcomegrid_github_evidence", Path(__file__).with_name("github_evidence.py"))
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)

REPO = "canoydario847-cloud/Privi-Network"
SHA = "a" * 40
CHECK = "outcomegrid-sandbox"
def snapshot():
    return {"repository": REPO, "head_sha": SHA, "total_count": 1,
            "check_runs": [{"name": CHECK, "id": 123, "head_sha": SHA,
                            "status": "completed", "conclusion": "success",
                            "app": {"slug": "github-actions"}}]}

class GitHubEvidenceTests(unittest.TestCase):
    def check(self, data):
        return e.verify_check_runs(data, repo=REPO, head_sha=SHA, required_checks=[CHECK])

    def test_pinned_success_only_produces_review_candidate(self):
        result = self.check(snapshot())
        self.assertTrue(result["valid"])
        self.assertEqual(result["state"], "checks_passed_awaiting_independent_review")
        self.assertFalse(result["scoreboard_eligible"])
        self.assertEqual(len(result["snapshot_sha256"]), 64)

    def test_reject_repo_or_sha_mismatch(self):
        for key, value in [("repository", "untrusted/other"), ("head_sha", "b"*40)]:
            data = snapshot()
            data[key] = value
            self.assertFalse(self.check(data)["valid"])

    def test_reject_failing_pending_and_skipped(self):
        for name, value in [("conclusion", "failure"), ("conclusion", "skipped"),
                            ("status", "queued"), ("head_sha", "b"*40)]:
            data = snapshot()
            data["check_runs"][0][name] = value
            self.assertFalse(self.check(data)["valid"])

    def test_reject_missing_duplicate_and_incomplete(self):
        data = snapshot()
        data["check_runs"] = []
        self.assertFalse(self.check(data)["valid"])
        data = snapshot()
        data["total_count"] = 2
        self.assertFalse(self.check(data)["valid"])
        data = snapshot()
        data["check_runs"].append(copy.deepcopy(data["check_runs"][0]))
        data["total_count"] = 2
        self.assertFalse(self.check(data)["valid"])

    def test_no_untrusted_scoreboard_credit(self):
        data = snapshot()
        result = self.check(data)
        self.assertNotIn("decision", result)
        self.assertFalse(result["scoreboard_eligible"])

    def test_strict_criteria(self):
        with self.assertRaises(ValueError):
            e.verify_check_runs(snapshot(), repo="bad repo", head_sha=SHA, required_checks=[CHECK])
        with self.assertRaises(ValueError):
            e.verify_check_runs(snapshot(), repo=REPO, head_sha=SHA, required_checks=[CHECK, CHECK])


if __name__ == "__main__":
    unittest.main()
