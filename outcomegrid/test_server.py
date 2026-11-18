"""HTTP regression tests for the public synthetic OutcomeGrid fixture server."""
import http.client
import importlib.util
import json
from pathlib import Path
import threading
import unittest
from http.server import ThreadingHTTPServer

spec = importlib.util.spec_from_file_location("outcomegrid_server", Path(__file__).with_name("server.py"))
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def call(self, method, path, body=None, content_type="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            c.request(method, path, body, {"Content-Type": content_type})
            r = c.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            c.close()

    def scenario(self, value):
        status, _, body = self.call("POST", "/api/simulate", json.dumps({"scenario": value}))
        self.assertEqual(status, 200)
        return json.loads(body)

    def test_cosmic_ui_brand_and_navigation(self):
        status, headers, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"hero-visual", body)
        self.assertIn(b"MISSION CONTROL", body)
        self.assertIn(b"privi-one-demo.onrender.com", body)
        self.assertIn(b"SYNTHETIC", body)

    def test_page_and_health(self):
        status, headers, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"PRELAUNCH", body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, _, body = self.call("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_accept_and_reject(self):
        accepted = self.scenario("accepted")
        self.assertEqual(accepted["outcome"]["decision"], "accepted")
        self.assertEqual(accepted["reputation"]["agents"][0]["accepted"], 1)
        rejected = self.scenario("rejected")
        self.assertEqual(rejected["outcome"]["decision"], "rejected")
        self.assertEqual(rejected["reputation"]["agents"][0]["accepted"], 0)
        self.assertEqual(accepted["payment"], "NOT_USED")

    def test_github_evidence_still_requires_review(self):
        fixture = self.scenario("github_checks_pending_review")
        self.assertTrue(fixture["github_check_evidence"]["valid"])
        self.assertTrue(fixture["review_required"])
        self.assertFalse(fixture["github_check_evidence"]["scoreboard_eligible"])
        self.assertIsNone(fixture["outcome"]["decision"])
        self.assertEqual(fixture["reputation"]["agents"], [])

    def test_self_attestation_and_duplicate_blocking(self):
        a = self.scenario("self_attestation_blocked")
        self.assertEqual(a["blocked_reason"], "executor_cannot_verify_self")
        self.assertEqual(a["reputation"]["agents"], [])
        b = self.scenario("duplicate_blocked")
        self.assertEqual(b["blocked_reason"], "duplicate_outcome_refused")
        self.assertEqual(b["reputation"]["agents"][0]["verified_total"], 1)

    def test_reject_arbitrary_verification_and_money_routes(self):
        bad = [
            ("/api/simulate", json.dumps({"scenario": "real_payout"})),
            ("/api/simulate", json.dumps({"scenario": "accepted", "actor": "attacker"})),
            ("/api/simulate", "not json"),
        ]
        for path, body in bad:
            status, _, _ = self.call("POST", path, body)
            self.assertEqual(status, 400)
        status, _, _ = self.call("POST", "/api/payouts", "{}")
        self.assertEqual(status, 404)
        status, _, _ = self.call("POST", "/api/outcomes", "{}")
        self.assertEqual(status, 404)

    def test_size_and_content_type(self):
        status, _, _ = self.call("POST", "/api/simulate", "x" * 300)
        self.assertEqual(status, 413)
        status, _, _ = self.call("POST", "/api/simulate", "{}",
                                  content_type="text/plain")
        self.assertEqual(status, 415)


if __name__ == "__main__":
    unittest.main()
