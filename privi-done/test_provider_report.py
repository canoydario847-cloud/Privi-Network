"""Provider report correlation regression tests. No external network calls."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "done_provider_report", Path(__file__).with_name("provider_report.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

REPO = "example/hello"
SHA = "a" * 40
SID = "srv-example123"
CHECKS = ["build", "security"]


def github():
    return {
        "schema": "privi-done-github-checks-v1",
        "source": "github-check-runs-api", "repository": REPO, "commit_sha": SHA,
        "result": "REPORTED_CHECKS_SUCCESS_DEPLOYMENT_UNVERIFIED",
        "required_checks": [
            {"name": "build", "result": "success", "run_id": 1},
            {"name": "security", "result": "success", "run_id": 2}],
        "check_count": 2, "deployment_verified": False,
        "cost_verified": False, "author_verified": False
    }


def render():
    return {
        "schema": "privi-done-render-v1", "repository": REPO,
        "service_id": SID, "expected_commit": SHA, "observed_commit": SHA,
        "latest_status": "live", "latest_deploy_id": "dep-test",
        "reported_live_commit_matches": True,
        "result": "RENDER_REPORTS_LIVE_COMMIT_HEALTH_UNVERIFIED",
        "independent_health_verified": False, "cost_verified": False,
        "customer_outcome_certified": False
    }


class ProviderCorrelationTests(unittest.TestCase):
    def report(self, gh=None, rd=None):
        return mod.assess_provider_reports(
            REPO, SHA, SID, CHECKS, github() if gh is None else gh,
            render() if rd is None else rd)

    def test_matching_reports_still_not_completed(self):
        result = self.report()
        self.assertEqual(result["status"], "PROVIDER_REPORTS_MATCH_OUTCOME_PENDING")
        self.assertFalse(result["completed"])
        self.assertFalse(result["verified_customer_outcome"])
        self.assertFalse(result["invoiceable_as_verified_outcome"])
        self.assertTrue(result["human_review_required"])
        self.assertEqual(len(result["report_sha256"]), 64)

    def test_customer_markdown_clearly_states_missing_evidence(self):
        markdown = mod.render_customer_markdown(self.report())
        for value in ("Not certified as completed", "No independently checked endpoint",
                      "not a signature", SHA, SID, "customer acceptance"):
            self.assertIn(value.lower(), markdown.lower())

    def test_wrong_github_commit_or_check_name_fails(self):
        for field, value in (("commit_sha", "b" * 40),
                             ("result", "FAIL_CI_EVIDENCE")):
            gh = github()
            gh[field] = value
            with self.subTest(field=field):
                self.assertEqual(self.report(gh=gh)["status"], "PROVIDER_EVIDENCE_FAILED")
        gh = github()
        gh["required_checks"][1]["name"] = "another"
        self.assertEqual(self.report(gh=gh)["status"], "PROVIDER_EVIDENCE_FAILED")

    def test_wrong_render_commit_or_service_fails(self):
        for field, value in (("observed_commit", "b" * 40),
                             ("service_id", "srv-unexpected"),
                             ("latest_status", "build_failed"),
                             ("reported_live_commit_matches", False)):
            rd = render()
            rd[field] = value
            with self.subTest(field=field):
                self.assertEqual(self.report(rd=rd)["status"], "PROVIDER_EVIDENCE_FAILED")

    def test_fabricated_verification_flags_rejected(self):
        gh = github()
        gh["deployment_verified"] = True
        self.assertEqual(self.report(gh=gh)["status"], "PROVIDER_EVIDENCE_FAILED")
        rd = render()
        rd["independent_health_verified"] = True
        self.assertEqual(self.report(rd=rd)["status"], "PROVIDER_EVIDENCE_FAILED")

    def test_invalid_identity_and_payload_rejected(self):
        with self.assertRaises(ValueError):
            mod.assess_provider_reports(REPO, "main", SID, CHECKS, github(), render())
        with self.assertRaises(ValueError):
            mod.assess_provider_reports(REPO, SHA, SID, CHECKS, [], render())
        with self.assertRaises(ValueError):
            mod.render_customer_markdown({"completed": True})

    def test_deterministic_report_and_no_customer_secrets(self):
        a, b = self.report(), self.report()
        self.assertEqual(a, b)
        self.assertNotIn("api_key", mod.render_customer_markdown(a))
        self.assertNotIn("token", mod.render_customer_markdown(a).lower())


if __name__ == "__main__":
    unittest.main()
