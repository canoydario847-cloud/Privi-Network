"""Security-focused offline tests for read-only GitHub check-run collection."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "privi_done_github_checks", Path(__file__).with_name("github_checks.py"))
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
SHA = "a" * 40


def run(name, status="completed", conclusion="success", ident=1, sha=SHA):
    return {"name": name, "status": status, "conclusion": conclusion,
            "id": ident, "head_sha": sha}


def transport(results, *, total=None):
    def fetch(path):
        assert path.startswith("/repos/example/hello/commits/" + SHA)
        page = int(path.rsplit("page=", 1)[-1])
        start = (page - 1) * 100
        return {"total_count": len(results) if total is None else total,
                "check_runs": results[start:start + 100]}
    return fetch


class GitHubChecksTests(unittest.TestCase):
    def test_successful_pinned_checks_not_deployment_verified(self):
        report = checks.collect_checks("example/hello", SHA, ["build", "security"],
            fetch=transport([run("build"), run("security", ident=2)]))
        self.assertEqual(report["result"], "REPORTED_CHECKS_SUCCESS_DEPLOYMENT_UNVERIFIED")
        self.assertFalse(report["deployment_verified"])
        self.assertFalse(report["cost_verified"])

    def test_missing_pending_skipped_failure_fail_closed(self):
        for variant in ([], [run("build", "in_progress", None)],
                        [run("build", conclusion="skipped")],
                        [run("build", conclusion="failure")]):
            with self.subTest(variant=variant):
                report = checks.collect_checks("example/hello", SHA, ["build"],
                                               fetch=transport(variant))
                self.assertEqual(report["result"], "FAIL_CI_EVIDENCE")

    def test_pagination_101_checks_complete(self):
        results = [run("check-" + str(i), ident=i+1) for i in range(101)]
        report = checks.collect_checks("example/hello", SHA, ["check-100"],
                                       fetch=transport(results))
        self.assertEqual(report["check_count"], 101)
        self.assertEqual(report["result"], "REPORTED_CHECKS_SUCCESS_DEPLOYMENT_UNVERIFIED")

    def test_incomplete_page_rejected(self):
        with self.assertRaisesRegex(checks.EvidenceUnavailable, "incomplete"):
            checks.collect_checks("example/hello", SHA, ["build"],
                                  fetch=transport([run("build")], total=2))

    def test_mismatched_sha_rejected(self):
        with self.assertRaisesRegex(checks.EvidenceUnavailable, "incorrectly pinned"):
            checks.collect_checks("example/hello", SHA, ["build"],
                fetch=transport([run("build", sha="b" * 40)]))

    def test_duplicate_check_names_rejected(self):
        with self.assertRaisesRegex(checks.EvidenceUnavailable, "duplicate"):
            checks.collect_checks("example/hello", SHA, ["build"],
                fetch=transport([run("build"), run("build", ident=2)]))

    def test_bad_json_shape_and_count_rejected(self):
        for reply in ({}, {"total_count": True, "check_runs": []},
                      {"total_count": 1, "check_runs": "bad"},
                      {"total_count": 2001, "check_runs": []}):
            with self.subTest(reply=reply):
                with self.assertRaises(checks.EvidenceUnavailable):
                    checks.collect_checks("example/hello", SHA, ["build"],
                                          fetch=lambda _path: reply)

    def test_bad_pinned_inputs_rejected_without_fetch(self):
        for repo, sha, names in (("https://evil.test/a", SHA, ["build"]),
                                 ("other/../../repo", SHA, ["build"]),
                                 ("example/hello", "main", ["build"]),
                                 ("example/hello", SHA, []),
                                 ("example/hello", SHA, ["build", "build"])):
            with self.subTest(repo=repo, sha=sha, names=names):
                with self.assertRaises(checks.EvidenceUnavailable):
                    checks.collect_checks(repo, sha, names,
                        fetch=lambda path: self.fail("must not fetch invalid inputs"))

    def test_transport_failures_not_misreported_as_success(self):
        def unavailable(_):
            raise checks.EvidenceUnavailable("upstream unavailable")
        with self.assertRaisesRegex(checks.EvidenceUnavailable, "unavailable"):
            checks.collect_checks("example/hello", SHA, ["build"], fetch=unavailable)


if __name__ == "__main__":
    unittest.main()
