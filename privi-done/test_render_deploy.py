"""No-network adversarial tests for Render deployment reporting."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("done_render_deploy",
    Path(__file__).with_name("render_deploy.py"))
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)
SERVICE = "srv-abc12345"
REPO = "example/hello"
SHA = "a" * 40


def fixture(*, sha=SHA, status="live", repo="https://github.com/example/hello",
            multiple=False):
    service = {"id": SERVICE, "repo": repo}
    deploys = [{"deploy": {"id": "dep-new", "status": status,
                            "createdAt": "2026-11-18T20:00:00Z",
                            "commit": {"id": sha}}}]
    if multiple:
        deploys.append({"deploy": {"id": "dep-old", "status": "live",
                                   "createdAt": "2026-11-17T20:00:00Z",
                                   "commit": {"id": "b" * 40}}})
    return lambda path: service if path == "/v1/services/" + SERVICE else deploys


class RenderReadOnlyTests(unittest.TestCase):
    def test_live_exact_commit_is_reported_not_health_certified(self):
        report = render.inspect_deployment(SERVICE, REPO, SHA, fetch=fixture())
        self.assertEqual(report["result"], "RENDER_REPORTS_LIVE_COMMIT_HEALTH_UNVERIFIED")
        self.assertTrue(report["reported_live_commit_matches"])
        self.assertFalse(report["independent_health_verified"])
        self.assertFalse(report["cost_verified"])

    def test_other_commit_and_pending_latest_fail_closed(self):
        for provider in (fixture(sha="b" * 40), fixture(status="build_in_progress"),
                         fixture(status="deactivated"), fixture(status="build_failed"),
                         fixture(multiple=True)):
            with self.subTest(provider=provider):
                report = render.inspect_deployment(SERVICE, REPO, SHA, fetch=provider)
                self.assertEqual(report["result"], "RENDER_DEPLOY_UNVERIFIED")

    def test_wrong_repository_and_service_rejected(self):
        for provider in (
            fixture(repo="https://github.com/other/hello"),
            fixture(repo="https://github.com.evil.test/example/hello"),
            fixture(repo="https://github.com/example/hello/"),
        ):
            with self.subTest(provider=provider):
                with self.assertRaisesRegex(
                    render.RenderEvidenceUnavailable, "repository"
                ):
                    render.inspect_deployment(SERVICE, REPO, SHA, fetch=provider)
        with self.assertRaisesRegex(render.RenderEvidenceUnavailable, "identity"):
            render.inspect_deployment(SERVICE, REPO, SHA,
                fetch=lambda path: {"id": "srv-different", "repo": "https://github.com/example/hello"})

    def test_invalid_service_or_sha_does_not_call_api(self):
        for service, repo, sha in (
            ("https://evil", REPO, SHA),
            ("srv-../../x", REPO, SHA),
            (SERVICE, "https://evil/a", SHA),
            (SERVICE, REPO, "main"),
        ):
            with self.subTest(service=service, repo=repo, sha=sha):
                with self.assertRaises(render.RenderEvidenceUnavailable):
                    render.inspect_deployment(service, repo, sha,
                        fetch=lambda path: self.fail("must not fetch bad input"))

    def test_missing_or_duplicate_or_malformed_deploys_fail_closed(self):
        base_service = {"id": SERVICE, "repo": "https://github.com/example/hello"}
        bad_cases = (
            [], [{"deploy": {}}],
            [{"deploy": {"id": "dep-1", "status": "live", "commit": {"id": SHA}}}],
            [{"deploy": {"id": "dep-1", "status": "live",
                         "createdAt": "2026-11-18T20:00:00Z",
                         "commit": {"id": SHA}}}] * 2
        )
        for deployments in bad_cases:
            with self.subTest(deployments=deployments):
                with self.assertRaises(render.RenderEvidenceUnavailable):
                    render.inspect_deployment(SERVICE, REPO, SHA,
                        fetch=lambda path: base_service
                        if path == "/v1/services/" + SERVICE else deployments)

    def test_older_matching_deploy_does_not_override_newer_failure(self):
        service = {"id": SERVICE, "repo": "https://github.com/example/hello"}
        entries = [
            {"deploy": {"id": "dep-older", "status": "live",
                        "createdAt": "2026-11-17T00:00:00Z",
                        "commit": {"id": SHA}}},
            {"deploy": {"id": "dep-newer", "status": "build_failed",
                        "createdAt": "2026-11-18T00:00:00Z",
                        "commit": {"id": SHA}}}
        ]
        report = render.inspect_deployment(SERVICE, REPO, SHA,
            fetch=lambda path: service if path == "/v1/services/" + SERVICE else entries)
        self.assertEqual(report["latest_status"], "build_failed")
        self.assertFalse(report["reported_live_commit_matches"])


if __name__ == "__main__":
    unittest.main()
