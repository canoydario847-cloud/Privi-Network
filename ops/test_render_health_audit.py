"""Offline tests for the read-only Privi Render health audit.

Run: python3 -m unittest discover -s ops -p 'test_render_health_audit.py'
No test sends an HTTP request to a live service.
"""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from ops import render_health_audit as audit


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, n):
        assert n == 128
        return b"ok"


class HealthAuditTests(unittest.TestCase):
    def test_get_success_reads_at_most_128_bytes(self):
        with patch.object(audit, "urlopen", return_value=FakeResponse()) as request:
            result = audit.check("privi-ledger", audit.PAID_APIS["privi-ledger"], 4.5)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], 200)
        args, kwargs = request.call_args
        self.assertEqual(kwargs["timeout"], 4.5)
        self.assertEqual(args[0].get_method(), "GET")

    def test_get_http_502_is_reported(self):
        failure = HTTPError("https://example.invalid/health", 502, "Bad Gateway", {}, None)
        with patch.object(audit, "urlopen", side_effect=failure):
            result = audit.check("privi-ledger", audit.PAID_APIS["privi-ledger"], 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 502)

    def test_network_errors_are_failures_without_secrets(self):
        with patch.object(audit, "urlopen", side_effect=URLError("test-network-failure")):
            result = audit.check("privi-ledger", audit.PAID_APIS["privi-ledger"], 2)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["status"])
        self.assertEqual(result["error"], "URLError")

    def run_cli(self, args):
        output = io.StringIO()
        with patch.object(audit, "check", return_value={"name": "test", "ok": True, "status": 200}) as checker:
            with contextlib.redirect_stdout(output):
                status = audit.main(args)
        return status, json.loads(output.getvalue()), checker

    def test_default_never_wakes_free_services(self):
        status, report, checker = self.run_cli([])
        self.assertEqual(status, 0)
        self.assertEqual(checker.call_count, len(audit.PAID_APIS))
        self.assertEqual(report["failures"], 0)
        self.assertEqual({call.args[0] for call in checker.call_args_list},
                         set(audit.PAID_APIS))

    def test_free_services_are_explicit_opt_in(self):
        _, _, checker = self.run_cli(["--include-free"])
        self.assertEqual(checker.call_count, len(audit.PAID_APIS) + len(audit.FREE_SERVICES))

    def test_static_sites_are_explicit_opt_in(self):
        _, _, checker = self.run_cli(["--all-sites"])
        self.assertEqual(checker.call_count, len(audit.PAID_APIS) + len(audit.STATIC_SITES))

    def test_all_endpoints_are_covered_if_both_flags_set(self):
        _, report, checker = self.run_cli(["--include-free", "--all-sites"])
        self.assertTrue(report["read_only"])
        self.assertEqual(checker.call_count,
                         len(audit.PAID_APIS) + len(audit.FREE_SERVICES) + len(audit.STATIC_SITES))

    def test_failing_http_request_sets_nonzero_exit_status(self):
        response = {"name": "privi-ledger", "ok": False, "status": 503}
        output = io.StringIO()
        with patch.object(audit, "check", return_value=response):
            with contextlib.redirect_stdout(output):
                status = audit.main([])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["failures"], len(audit.PAID_APIS))

    def test_rejects_invalid_timeout(self):
        for value in ["0", "-1", "121"]:
            with self.subTest(value=value):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as failure:
                        audit.main(["--timeout", value])
                self.assertEqual(failure.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
