"""Offline native PRVI supply arithmetic invariants (not runtime enforcement).

Run: python3 -m unittest production-network/ops/test_prvi_supply_arithmetic.py
The production SDK mint/burn/bank paths still require independent review.
"""
import unittest

MAX_PRVI = 1_000_000_000
BASE_UNITS_PER_PRVI = 10**18
CAP_BASE_UNITS = MAX_PRVI * BASE_UNITS_PER_PRVI


def validate_supply(genesis_base_units, minted_base_units, burned_base_units):
    """Return current supply; reject invalid values and lifetime cap breaches.

    Burned tokens do not restore lifetime minting headroom.
    """
    values = (genesis_base_units, minted_base_units, burned_base_units)
    if any(type(v) is not int or v < 0 for v in values):
        raise ValueError("supply counters must be nonnegative integers")
    lifetime_issued = genesis_base_units + minted_base_units
    if lifetime_issued > CAP_BASE_UNITS:
        raise ValueError("lifetime PRVI issuance exceeds cap")
    if burned_base_units > lifetime_issued:
        raise ValueError("burn exceeds lifetime issuance")
    return lifetime_issued - burned_base_units


class SupplyArithmeticTests(unittest.TestCase):
    def test_exact_cap_allowed(self):
        self.assertEqual(validate_supply(CAP_BASE_UNITS, 0, 0), CAP_BASE_UNITS)

    def test_genesis_and_post_genesis_mint_share_one_lifetime_cap(self):
        self.assertEqual(validate_supply(CAP_BASE_UNITS - 7, 7, 0), CAP_BASE_UNITS)
        with self.assertRaises(ValueError):
            validate_supply(CAP_BASE_UNITS - 7, 8, 0)

    def test_one_base_unit_over_cap_rejected(self):
        with self.assertRaises(ValueError):
            validate_supply(CAP_BASE_UNITS, 1, 0)

    def test_burning_does_not_restore_issuance_headroom(self):
        with self.assertRaises(ValueError):
            validate_supply(CAP_BASE_UNITS, 1, 1)

    def test_burn_cannot_exceed_issued(self):
        with self.assertRaises(ValueError):
            validate_supply(0, 0, 1)

    def test_reject_boolean_fraction_and_negative_counters(self):
        for invalid in (True, 1.5, -1, "1"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_supply(invalid, 0, 0)

    def test_valid_burn_reduces_circulating_supply(self):
        self.assertEqual(validate_supply(10, 5, 4), 11)


if __name__ == "__main__":
    unittest.main()
