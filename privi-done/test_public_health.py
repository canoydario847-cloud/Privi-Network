"""Offline tests for constrained public sandbox health observation."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "done_public_health", Path(__file__).with_name("public_health.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class PublicHealthTests(unittest.TestCase):
    def test_expected_health_is_a_limited_observation(self):
        result = mod.inspect_privi_one_health(read=lambda: {
            "ok": True, "service": "privi-one-demo", "mode": "PRELAUNCH_SIMULATION"})
        self.assertEqual(result["result"], "PRIVI_ONE_SANDBOX_HEALTH_REPORTED")
        self.assertTrue(result["http_health_reported"])
        self.assertFalse(result["expected_commit_verified"])
        self.assertFalse(result["customer_outcome_certified"])
        self.assertEqual(result["endpoint"], "https://privi-one-demo.onrender.com/health")

    def test_forged_mode_or_service_fails(self):
        for response in ({"ok": True, "service": "other", "mode": "PRELAUNCH_SIMULATION"},
                         {"ok": True, "service": "privi-one-demo", "mode": "MAINNET"},
                         {"ok": False, "service": "privi-one-demo", "mode": "PRELAUNCH_SIMULATION"},
                         [], None):
            with self.subTest(response=response):
                self.assertEqual(
                    mod.inspect_privi_one_health(read=lambda: response)["result"],
                    "HEALTH_MISMATCH")

    def test_network_errors_are_fail_closed(self):
        def down():
            raise mod.HealthUnavailable("unreachable")
        r = mod.inspect_privi_one_health(read=down)
        self.assertEqual(r["result"], "HEALTH_UNAVAILABLE")
        self.assertFalse(r["http_health_reported"])

    def test_observer_never_accepts_arbitrary_urls(self):
        with self.assertRaises(TypeError):
            mod.inspect_privi_one_health(url="http://127.0.0.1/metadata")

    def test_test_mode_is_never_mistaken_for_financial_mainnet(self):
        r = mod.inspect_privi_one_health(read=lambda: {
            "ok": True, "service": "privi-one-demo", "mode": "PRELAUNCH_SIMULATION"})
        self.assertFalse(r["expected_commit_verified"])
        self.assertNotIn("MAINNET_READY", str(r))


if __name__ == "__main__":
    unittest.main()
