"""Privi ONE short-lived quote authentication tests (all synthetic)."""
import hashlib
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).with_name("quote_integrity.py")
spec = importlib.util.spec_from_file_location("privi_one_quote_integrity_tests", PATH)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)
KEY = b"local-test-only-quote-key-with-32-or-more-bytes"
TASK = hashlib.sha256(b"synthetic task").hexdigest()
OPTIONS = [{"id":"local-fixture","cost_cents":5,"quality":90,"reliability":99,"latency_ms":800}]


class QuoteTests(unittest.TestCase):
    def test_valid_short_lived_fixture(self):
        bundle = q.issue(OPTIONS, TASK, key=KEY, now=1000, ttl_seconds=120)
        self.assertTrue(q.verify(bundle, TASK, key=KEY, now=1050))
        self.assertFalse(q.verify(bundle, TASK, key=KEY, now=1121))

    def test_price_tamper_rejected(self):
        bundle = q.issue(OPTIONS, TASK, key=KEY, now=1000)
        bundle["body"]["options"][0]["cost_cents"] = 0
        self.assertFalse(q.verify(bundle, TASK, key=KEY, now=1050))

    def test_reject_malformed_options_at_issue_time(self):
        bad_cases = (
            [{"id": "bad", "cost_cents": -1, "quality": 90,
              "reliability": 99, "latency_ms": 800}],
            [{"id": "bad", "cost_cents": True, "quality": 90,
              "reliability": 99, "latency_ms": 800}],
            [{"id": "bad", "cost_cents": 5, "quality": 101,
              "reliability": 99, "latency_ms": 800}],
            [OPTIONS[0].copy(), OPTIONS[0].copy()],
            [{"id": "bad", "cost_cents": 5, "quality": 90,
              "reliability": 99, "latency_ms": 800,
              "name": {"unsafe": "type"}}],
        )
        for options in bad_cases:
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, "Invalid synthetic quote"):
                    q.issue(options, TASK, key=KEY, now=1000)

    def test_reject_locally_authenticated_malformed_options(self):
        # A local key can authenticate bad data; the verifier must still
        # independently reject malformed or duplicated synthetic quotes.
        import hmac
        for invalid in (
            [{**OPTIONS[0], "quality": 101}],
            [OPTIONS[0].copy(), OPTIONS[0].copy()],
            [{**OPTIONS[0], "cost_cents": -1}],
        ):
            with self.subTest(invalid=invalid):
                bundle = q.issue(OPTIONS, TASK, key=KEY, now=1000)
                bundle["body"]["options"] = invalid
                bundle["auth"]["mac"] = hmac.new(
                    KEY, q.canonical(bundle["body"]), hashlib.sha256
                ).hexdigest()
                self.assertFalse(q.verify(bundle, TASK, key=KEY, now=1050))

    def test_fingerprint_must_be_lowercase_sha256(self):
        with self.assertRaisesRegex(ValueError, "task fingerprint"):
            q.issue(OPTIONS, "Z" * 64, key=KEY, now=1000)
        valid = q.issue(OPTIONS, TASK, key=KEY, now=1000)
        self.assertFalse(q.verify(valid, "Z" * 64, key=KEY, now=1050))

    def test_extraneous_provenance_claims_rejected_even_when_locally_signed(self):
        import hmac
        for location, key, value in (
            ("option", "provider_verified", True),
            ("body", "live_provider_quote", True),
            ("auth", "independently_signed", True),
            ("envelope", "provider_signature", "not-real"),
        ):
            with self.subTest(location=location):
                bundle = q.issue(OPTIONS, TASK, key=KEY, now=1000)
                if location == "option":
                    bundle["body"]["options"][0][key] = value
                elif location == "body":
                    bundle["body"][key] = value
                elif location == "auth":
                    bundle["auth"][key] = value
                else:
                    bundle[key] = value
                bundle["auth"]["mac"] = hmac.new(
                    KEY, q.canonical(bundle["body"]), hashlib.sha256
                ).hexdigest()
                self.assertFalse(q.verify(bundle, TASK, key=KEY, now=1050))

    def test_reject_bad_issue_clock_and_boolean_lifetime(self):
        for now, ttl in ((True, 120), (-1, 120), (1.5, 120), (1000, True)):
            with self.subTest(now=now, ttl=ttl):
                with self.assertRaisesRegex(ValueError, "quote (timestamp|lifetime)"):
                    q.issue(OPTIONS, TASK, key=KEY, now=now, ttl_seconds=ttl)

    def test_local_quote_with_name_remains_valid(self):
        named = [{**OPTIONS[0], "name": "Synthetic fixture"}]
        bundle = q.issue(named, TASK, key=KEY, now=1000)
        self.assertTrue(q.verify(bundle, TASK, key=KEY, now=1050))

    def test_wrong_task_or_secret(self):
        bundle = q.issue(OPTIONS, TASK, key=KEY, now=1000)
        self.assertFalse(q.verify(bundle, "0"*64, key=KEY, now=1050))
        self.assertFalse(q.verify(bundle, TASK, key=b"different-test-key-length-over-32-bytes", now=1050))

    def test_future_or_bad_expiry(self):
        bundle = q.issue(OPTIONS, TASK, key=KEY, now=1000)
        self.assertFalse(q.verify(bundle, TASK, key=KEY, now=999))
        bundle["body"]["expires_at"] = 2000
        self.assertFalse(q.verify(bundle, TASK, key=KEY, now=1001))


if __name__ == "__main__":
    unittest.main()
