"""OutcomeGrid read-only GitHub collector unit tests; zero external API requests."""
import importlib.util
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("outcomegrid_github_collector", HERE / "github_collector.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

REPO = "canoydario847-cloud/Privi-Network"
SHA = "a" * 40
TOKEN = "synthetic-test-token-that-is-not-real"


def check(i, name="ci/test", conclusion="success", sha=SHA):
    return {"id": i, "name": name, "head_sha": sha,
            "status": "completed", "conclusion": conclusion,
            "app": {"slug": "github-actions"}}


class CollectorTests(unittest.TestCase):
    def fake(self, pages):
        urls = []
        def get_json(url):
            urls.append(url)
            u = urlparse(url)
            self.assertEqual(u.scheme, "https")
            self.assertEqual(u.netloc, "api.github.com")
            self.assertTrue(u.path.endswith("/commits/" + SHA + "/check-runs"))
            page = int(parse_qs(u.query)["page"][0])
            return pages[page - 1]
        return get_json, urls

    def collect(self, pages, checks=("ci/test",)):
        get_json, urls = self.fake(pages)
        output = mod.collect_and_review(
            REPO, SHA, list(checks), allowed_repo=REPO,
            token=TOKEN, get_json=get_json)
        return output, urls

    def test_pinned_success_creates_review_candidate(self):
        out, urls = self.collect([{"total_count": 1, "check_runs": [check(1)]}])
        self.assertTrue(out["valid"])
        self.assertEqual(out["state"], "checks_passed_awaiting_independent_review")
        self.assertFalse(out["scoreboard_eligible"])
        self.assertEqual(len(urls), 1)

    def test_two_pages_conservatively_collected(self):
        first = [check(i + 1, "other") for i in range(100)]
        second = [check(101)]
        out, urls = self.collect([
            {"total_count": 101, "check_runs": first},
            {"total_count": 101, "check_runs": second},
        ])
        self.assertTrue(out["valid"])
        self.assertEqual(len(urls), 2)

    def test_unapproved_repo_and_missing_token_denied_without_fetch(self):
        def forbidden(_):
            self.fail("network must not be called")
        with self.assertRaises(PermissionError):
            mod.collect(REPO, SHA, allowed_repo="other/repo",
                        token=TOKEN, get_json=forbidden)
        with self.assertRaises(PermissionError):
            mod.collect(REPO, SHA, allowed_repo=REPO,
                        token="", get_json=forbidden)

    def test_mismatch_and_failure_remain_untrusted(self):
        for run in (check(1, conclusion="failure"), check(1, sha="b" * 40)):
            out, _ = self.collect([{"total_count": 1, "check_runs": [run]}])
            self.assertFalse(out["valid"])

    def test_paginated_incomplete_or_inconsistent_fails(self):
        for pages in (
            [{"total_count": 2, "check_runs": [check(1)]},
             {"total_count": 3, "check_runs": [check(2)]}],
            [{"total_count": 2, "check_runs": [check(1)]},
             {"total_count": 2, "check_runs": []}],
        ):
            with self.assertRaises(RuntimeError):
                self.collect(pages)

    def test_reject_over_limit(self):
        with self.assertRaises(RuntimeError):
            self.collect([{"total_count": 1001, "check_runs": []}])

    def test_no_automatic_attestation_or_payout(self):
        out, _ = self.collect([{"total_count": 1, "check_runs": [check(1)]}])
        self.assertNotIn("outcome", out)
        self.assertNotIn("payment", out)
        self.assertNotIn("decision", out)


if __name__ == "__main__":
    unittest.main()
