#!/usr/bin/env python3
"""Unit tests for the disposable InitChain zero-allocation rejection gate."""
import unittest
from ci_init_chain_cap_negative import CAP_GUARD, is_expected_failure


class StartupCapTests(unittest.TestCase):
    def test_only_exact_supply_guard_counts(self):
        self.assertTrue(is_expected_failure(1, b"", CAP_GUARD.encode("ascii")))
        self.assertTrue(is_expected_failure(2, CAP_GUARD.encode("ascii"), b""))
        self.assertFalse(is_expected_failure(0, b"", CAP_GUARD.encode("ascii")))
        self.assertFalse(is_expected_failure(1, b"", b"panic: genesis invalid"))
        self.assertFalse(is_expected_failure(1, b"", b"mint genesis has invalid params"))
        self.assertFalse(is_expected_failure(1, b"", b"PRVI supply above fixed maximum"))
        self.assertFalse(is_expected_failure(1, b"", b"cosmos id missing"))
        self.assertFalse(is_expected_failure(None, b"", CAP_GUARD.encode("ascii")))

    def test_untrusted_log_types_never_count(self):
        self.assertFalse(is_expected_failure(1, "incorrect string", b""))
        self.assertFalse(is_expected_failure(1, b"", "incorrect string"))
        self.assertFalse(is_expected_failure(1, None, b""))


if __name__ == "__main__":
    unittest.main()
