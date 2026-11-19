"""Offline, fail-closed tests for exact Privi ONE version observation."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "privi_done_version_observer", Path(__file__).with_name("version_observer.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SHA = "a" * 40


def healthy(sha=SHA):
    return {"service": "privi-one-demo",
            "mode": "PRELAUNCH_SIMULATION",
            "version_source": "RENDER_GIT_COMMIT_ENV",
            "self_reported_commit": sha,
            "independently_attested": False}


class VersionObservationTests(unittest.TestCase):
    def test_pinned_match_is_not_execution_attestation(self):
        report = mod.inspect_version(SHA, read=lambda: healthy())
        self.assertTrue(report["server_self_report_matches"])
        self.assertFalse(report["execution_cryptographically_attested"])
        self.assertFalse(report["customer_outcome_certified"])
        self.assertEqual(report["result"], "SELF_REPORTED_VERSION_MATCH_UNATTESTED")

    def test_wrong_or_missing_commit_fails_closed(self):
        for body in (healthy("b" * 40), healthy(None),
                     dict(healthy(), mode="MAINNET"),
                     dict(healthy(), version_source="UNAVAILABLE"),
                     dict(healthy(), independently_attested=True),
                     {"service": "privi-one-demo"}, None):
            with self.subTest(body=body):
                self.assertFalse(mod.inspect_version(
                    SHA, read=lambda: body)["server_self_report_matches"])

    def test_malformed_sha_never_reads_network(self):
        for candidate in ("main", "A" * 40, "../" + "a" * 40):
            with self.assertRaises(ValueError):
                mod.inspect_version(candidate,
                    read=lambda: self.fail("network read not allowed"))

    def test_unavailable_response_does_not_become_success(self):
        def down():
            raise TimeoutError("cold start")
        report = mod.inspect_version(SHA, read=down)
        self.assertEqual(report["result"], "VERSION_MISMATCH_OR_UNAVAILABLE")
        self.assertFalse(report["server_self_report_matches"])

    def test_extra_unsigned_claims_fail_closed(self):
        payload = dict(healthy(), user_verified=True)
        self.assertFalse(mod.inspect_version(
            SHA, read=lambda: payload)["server_self_report_matches"])


if __name__ == "__main__":
    unittest.main()
