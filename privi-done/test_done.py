"""Offline test vectors for DONE and Code Origin (standard library)."""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


done = load("deployment_verifier")
origin = load("code_origin")
KEY = b"ONLY-TEST-FIXTURE-NOT-A-PRODUCTION-IDENTITY-KEY"


def intent():
    return {"repository": "example/hello", "commit_sha": "a" * 40,
            "required_checks": ["build", "security"], "expected_version": "v1",
            "max_cost_cents": 2000}


def evidence():
    return {"repository": "example/hello", "commit_sha": "a" * 40,
            "checks": [{"name": "build", "conclusion": "success"},
                       {"name": "security", "conclusion": "success"}],
            "observed_version": "v1",
            "probes": [{"name": "GET /health", "passed": True}],
            "cost_cents": 1500, "complete": True}


class DoneVerificationTests(unittest.TestCase):
    def test_matching_report_never_claims_external_verification(self):
        report = done.assess_deployment(intent(), evidence())
        self.assertEqual(report["result"], "PASS_PENDING_INDEPENDENT_VERIFICATION")
        self.assertFalse(report["independent_execution_verified"])
        self.assertFalse(report["customer_outcome_certified"])
        self.assertFalse(report["payment_verified"])
        self.assertEqual(report, done.assess_deployment(intent(), evidence()))

    def test_wrong_commit_and_version_rejected(self):
        item = evidence()
        item["commit_sha"] = "b" * 40
        item["observed_version"] = "v0"
        report = done.assess_deployment(intent(), item)
        self.assertIn("pinned-repository-or-commit-mismatch", report["issues"])
        self.assertIn("deployed-version-mismatch", report["issues"])

    def test_missing_pending_and_skipped_check_fail_closed(self):
        for conclusion in ("pending", "skipped", "failure", "cancelled"):
            with self.subTest(conclusion=conclusion):
                item = evidence()
                item["checks"][1]["conclusion"] = conclusion
                self.assertEqual(done.assess_deployment(intent(), item)["result"], "FAIL")

    def test_probe_failure_cost_limit_and_partial_evidence(self):
        item = evidence()
        item["probes"][0]["passed"] = False
        item["cost_cents"] = 2001
        item["complete"] = False
        report = done.assess_deployment(intent(), item)
        self.assertIn("probe-failed:GET /health", report["issues"])
        self.assertIn("cost-cap-exceeded", report["issues"])
        self.assertIn("incomplete-evidence", report["issues"])

    def test_untrusted_input_shapes_rejected(self):
        for modification in ({"cost_cents": True}, {"probes": []},
                             {"checks": [{"name": "build", "conclusion": "success"}] * 2},
                             {"complete": "yes"}):
            with self.subTest(modification=modification):
                item = evidence()
                item.update(modification)
                if modification.get("probes") == []:
                    self.assertEqual(done.assess_deployment(intent(), item)["result"], "FAIL")
                else:
                    with self.assertRaises(ValueError):
                        done.assess_deployment(intent(), item)


class CodeOriginTests(unittest.TestCase):
    def setUp(self):
        self.source = "def human():\n    return 1\ndef agent():\n    return 2\n"

    def manifest(self):
        return origin.make_test_attestation(
            self.source, [(1, 2, "human"), (3, 4, "agent")],
            "fixture-pinned-reviewer", KEY)

    def test_unattributed_code_is_unknown_not_ai_detected(self):
        result = origin.compare_code(self.source)
        self.assertEqual(result["attribution"], "UNKNOWN")
        self.assertEqual(result["counts"], {"human": 0, "agent": 0, "unknown": 4})

    def test_trusted_fixture_signature_produces_mixed_claims(self):
        result = origin.compare_code(
            self.source, self.manifest(), pinned_keys={"fixture-pinned-reviewer": KEY})
        self.assertEqual(result["attribution"], "MIXED")
        self.assertEqual(result["counts"], {"human": 2, "agent": 2, "unknown": 0})
        self.assertIn("NOT_INDEPENDENT_AUTHORSHIP_PROOF", result["evidence"])

    def test_untrusted_or_wrong_key_makes_all_lines_unknown(self):
        for keys in ({}, {"fixture-pinned-reviewer": b"z" * 32}):
            with self.subTest(keys=keys):
                result = origin.compare_code(self.source, self.manifest(), pinned_keys=keys)
                self.assertEqual(result["attribution"], "UNKNOWN")

    def test_tampered_code_and_manifest_do_not_assign_authorship(self):
        manifest = self.manifest()
        self.assertEqual(origin.compare_code(
            self.source.replace("return 2", "return 3"), manifest,
            pinned_keys={"fixture-pinned-reviewer": KEY})["attribution"], "UNKNOWN")
        manifest["ranges"][0]["category"] = "agent"
        self.assertEqual(origin.compare_code(
            self.source, manifest, pinned_keys={"fixture-pinned-reviewer": KEY}
        )["attribution"], "UNKNOWN")

    def test_overlap_rejected_and_unsigned_partial_claims_not_trusted(self):
        manifest = origin.make_test_attestation(
            self.source, [(1, 3, "human"), (3, 4, "agent")],
            "fixture-pinned-reviewer", KEY)
        self.assertEqual(origin.compare_code(
            self.source, manifest, pinned_keys={"fixture-pinned-reviewer": KEY}
        )["attribution"], "UNKNOWN")

    def test_verified_single_range_leaves_other_lines_unknown(self):
        manifest = origin.make_test_attestation(
            self.source, [(3, 4, "agent")], "fixture-pinned-reviewer", KEY)
        result = origin.compare_code(
            self.source, manifest, pinned_keys={"fixture-pinned-reviewer": KEY})
        self.assertEqual(result["attribution"], "AGENT")
        self.assertEqual(result["counts"], {"human": 0, "agent": 2, "unknown": 2})


if __name__ == "__main__":
    unittest.main()
