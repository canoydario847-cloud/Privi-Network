"""Pilot acceptance scope tests: never convert HTTP checks into customer acceptance."""
import importlib.util
from pathlib import Path
import unittest

def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name+".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

review = load("pilot_review")
functional = load("functional_acceptance")
SHA = "7d4299ab717e7cbd13344b1950127f574836d3dc"
ZERO = "0"*64

def scope():
    return {
        "pilot_id": "PRIVI-ONE-INTERNAL-01",
        "scope_owner": "Privi World Corp (internal test)",
        "repository": "canoydario847-cloud/Privi-Network",
        "service_id": "srv-dbvlkvt9el5s73a5dv80",
        "expected_commit": SHA,
        "required_observations": [
            "sandbox_health", "version_self_report",
            "local_journal_audit_reported", "unsigned_checkpoint_correlates"],
        "acceptance_policy": "HUMAN_SIGNOFF_REQUIRED_NO_AUTOBILL",
    }

def responses():
    return {
        "/health": {"ok": True, "service": "privi-one-demo",
                    "mode": "PRELAUNCH_SIMULATION"},
        "/api/version": {"service": "privi-one-demo", "mode": "PRELAUNCH_SIMULATION",
                         "version_source": "RENDER_GIT_COMMIT_ENV",
                         "self_reported_commit": SHA, "independently_attested": False},
        "/api/audit": {"valid": True, "entries_checked": 0, "head": ZERO,
                       "scope": "LOCAL_SQLITE_TAMPER_EVIDENCE_NOT_EXTERNAL_PROOF"},
        "/api/checkpoint": {"schema": "privi-one-external-checkpoint-v1",
                            "sequence": 0, "head": ZERO,
                            "mode": "LOCAL_SANDBOX_UNSIGNED_CHECKPOINT"},
    }

def observe(data=None):
    payload = responses() if data is None else data
    return functional.observe(SHA, get=lambda path: payload[path])

class PilotReviewTests(unittest.TestCase):
    def test_matching_scope_still_requires_human_acceptance(self):
        result = review.assess_pilot_scope(scope(), observe())
        self.assertTrue(result["criteria_observed"])
        self.assertEqual(result["result"], "CRITERIA_OBSERVED_AWAITING_OWNER_REVIEW")
        self.assertFalse(result["owner_accepted"])
        self.assertFalse(result["outcome_certified"])
        self.assertFalse(result["invoiceable"])

    def test_missing_required_condition(self):
        broken = responses()
        broken["/api/checkpoint"]["head"] = "f"*64
        result = review.assess_pilot_scope(scope(), observe(broken))
        self.assertEqual(result["result"], "CRITERIA_INCOMPLETE_OR_UNTRUSTED")

    def test_identity_mismatches_are_blocked(self):
        for key, bad in (("expected_commit", "main"), ("service_id", "srv-other"),
                         ("repository", "other/repo"),
                         ("acceptance_policy", "AUTO_BILL")):
            with self.subTest(key=key):
                item = scope()
                item[key] = bad
                with self.assertRaises(ValueError):
                    review.assess_pilot_scope(item, observe())

    def test_duplicate_and_unknown_check_rejected(self):
        for checks in ([], ["sandbox_health", "sandbox_health"],
                       ["customer_paid"], [1]):
            item = scope()
            item["required_observations"] = checks
            with self.subTest(checks=checks):
                with self.assertRaises(ValueError):
                    review.assess_pilot_scope(item, observe())

    def test_fabricated_observation_claims_not_accepted(self):
        for key in ("invoiceable", "customer_accepted", "execution_attested",
                    "journal_crypto_proof", "cost_verified"):
            data = observe()
            data[key] = True
            self.assertFalse(review.assess_pilot_scope(
                scope(), data)["criteria_observed"])

    def test_wrong_observation_sha_and_origin_fail(self):
        for key, value in (("origin", "https://evil.example"),
                           ("expected_sha", "a"*40),
                           ("schema", "fake")):
            payload = observe()
            payload[key] = value
            self.assertFalse(review.assess_pilot_scope(
                scope(), payload)["criteria_observed"])

    def test_markdown_clear_about_review_and_payment(self):
        result = review.assess_pilot_scope(scope(), observe())
        md = review.to_markdown(result)
        for value in ("Made by Dario Canoy", "No customer signoff",
                      "No invoice", "not a signature"):
            self.assertIn(value.lower(), md.lower())

    def test_markdown_refuses_forged_certification(self):
        result = review.assess_pilot_scope(scope(), observe())
        result["invoiceable"] = True
        with self.assertRaises(ValueError):
            review.to_markdown(result)

    def test_deterministic_digest(self):
        self.assertEqual(review.assess_pilot_scope(scope(), observe()),
                         review.assess_pilot_scope(scope(), observe()))

if __name__ == "__main__":
    unittest.main()
