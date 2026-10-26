"""Fail closed if checked-in LIFE sample configuration enables token payments.

This is a static regression guard, not a runtime financial safety audit.
"""
from pathlib import Path
import unittest

ENV = Path(__file__).resolve().parents[1] / ".env.example"
PAYMENT_SWITCHES = ("PRVI_MAINNET_PAYMENTS_ENABLED", "BNB_PRIV_PAYMENTS_ENABLED")
# The disposable preview must remain explicit in deployment, not implied by this sample.
STAGING_SWITCH = "LIFE_STAGING_ONLY"


def parse_defaults(text):
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep and key in PAYMENT_SWITCHES:
            values.setdefault(key, []).append(value.strip())
    return values


class PaymentDefaultSafetyTests(unittest.TestCase):
    def test_checked_in_sample_disables_all_real_token_gates(self):
        values = parse_defaults(ENV.read_text(encoding="utf-8"))
        for key in PAYMENT_SWITCHES:
            with self.subTest(key=key):
                self.assertEqual(values.get(key), ["0"], f"{key} must appear once and be 0")

    def test_staging_setting_is_explicit_and_boolean(self):
        values = [line.partition("=")[2].strip() for line in ENV.read_text(encoding="utf-8").splitlines() if line.strip().startswith(STAGING_SWITCH + "=")]
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0], "1", "sample config must default to disposable staging")

    def test_staging_flag_rejects_unsafe_examples(self):
        for text in ("LIFE_STAGING_ONLY=0", "LIFE_STAGING_ONLY=", "LIFE_STAGING_ONLY=1\\nLIFE_STAGING_ONLY=0", ""):
            values = [line.partition("=")[2].strip() for line in text.splitlines() if line.strip().startswith(STAGING_SWITCH + "=")]
            with self.subTest(text=text):
                self.assertNotEqual(values, ["1"])

    def test_duplicate_or_enabled_defaults_are_rejected(self):
        for text in (
            "PRVI_MAINNET_PAYMENTS_ENABLED=1\nBNB_PRIV_PAYMENTS_ENABLED=0",
            "PRVI_MAINNET_PAYMENTS_ENABLED=0\nPRVI_MAINNET_PAYMENTS_ENABLED=1\nBNB_PRIV_PAYMENTS_ENABLED=0",
            "PRVI_MAINNET_PAYMENTS_ENABLED=0",
        ):
            values = parse_defaults(text)
            self.assertFalse(all(values.get(k) == ["0"] for k in PAYMENT_SWITCHES))


if __name__ == "__main__":
    unittest.main()
