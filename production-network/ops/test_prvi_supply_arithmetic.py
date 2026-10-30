"""Offline native PRVI supply arithmetic invariants (not runtime enforcement).

Run: python3 -m unittest production-network/ops/test_prvi_supply_arithmetic.py
The production SDK mint/burn/bank paths still require independent review.
"""
import unittest
import re
import subprocess
import types
from pathlib import Path

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
    def test_cap_and_denom_match_genesis_preflight(self):
        # Prevent this independent arithmetic model from silently drifting
        # from the candidate genesis auditor's native token configuration.
        # CI's filtered checkout can omit the auditor from the worktree;
        # read the exact tracked source from HEAD, as its own tests do.
        source = subprocess.run(
            ["git", "show", "HEAD:production-network/ops/prvi_genesis_preflight.py"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, check=True,
        ).stdout
        auditor = types.ModuleType("prvi_genesis_preflight")
        exec(compile(source, "prvi_genesis_preflight.py", "exec"), auditor.__dict__)
        self.assertEqual(auditor.MAX_PRVI, MAX_PRVI)
        self.assertEqual(10 ** auditor.DECIMALS, BASE_UNITS_PER_PRVI)
        self.assertEqual(auditor.CAP, CAP_BASE_UNITS)
        self.assertEqual(auditor.DENOM, "aprvi")
        # Cross-check actual offline genesis validation, not just constants:
        # a self-consistent bank balance and declared supply over the cap
        # must still fail the native-supply gate.
        over_cap = str(CAP_BASE_UNITS + 1)
        genesis = {"app_state": {"bank": {
            "balances": [{"address": "prvi1offlinefixture", "coins": [
                {"denom": "aprvi", "amount": over_cap}]}],
            "supply": [{"denom": "aprvi", "amount": over_cap}],
        }}}
        errors, _ = auditor.check(genesis)
        self.assertTrue(
            any("exceeds 1B PRVI" in error for error in errors), errors
        )
        # Aggregate native allocations across accounts before applying the cap.
        # A declared bank supply matching balances must not conceal an overcap.
        bank = genesis["app_state"]["bank"]
        bank["balances"] = [
            {"address": "prvi1offlinefixture", "coins": [
                {"denom": "aprvi", "amount": str(CAP_BASE_UNITS - 1)}]},
            {"address": "prvi1offlinefixture2", "coins": [
                {"denom": "aprvi", "amount": "1"}]},
        ]
        bank["supply"][0]["amount"] = str(CAP_BASE_UNITS)
        errors, total = auditor.check(genesis)
        self.assertEqual(errors, [], errors)
        self.assertEqual(total, CAP_BASE_UNITS)
        bank["balances"][0]["coins"][0]["amount"] = str(CAP_BASE_UNITS)
        bank["supply"][0]["amount"] = str(CAP_BASE_UNITS + 1)
        errors, total = auditor.check(genesis)
        self.assertEqual(total, CAP_BASE_UNITS + 1)
        self.assertIn("native genesis supply exceeds 1B PRVI", errors)

    def test_offline_go_cap_constants_match_python_model(self):
        # Detect cross-language source drift, NOT consensus/runtime enforcement.
        repo_root = Path(__file__).resolve().parents[2]
        models = {
            "production-network/mainnet/capmodel/cap.go": {
                "BaseDenom": "aprvi",
                "Decimals": "18",
                "MaximumPRVI": str(MAX_PRVI),
                "MaximumBase": str(CAP_BASE_UNITS),
            },
            "production-network/mainnet/prvicap/keeper.go": {
                "BaseDenom": "aprvi",
                "Decimals": "18",
                "MaxWholePRVI": str(MAX_PRVI),
                "MaxBase": str(CAP_BASE_UNITS),
            },
        }
        for path, constants in models.items():
            # The filtered CI worktree may omit Go files; read tracked HEAD.
            source = subprocess.run(
                ["git", "show", f"HEAD:{path}"],
                cwd=repo_root, capture_output=True, text=True, check=True,
            ).stdout
            for name, expected in constants.items():
                with self.subTest(path=path, constant=name):
                    matches = re.findall(
                        rf'(?m)^[ \t]*{re.escape(name)}[ \t]*=[ \t]*(?:"([^"\n]+)"|([0-9]+))[ \t]*(?://[^\n]*)?$',
                        source,
                    )
                    self.assertEqual(len(matches), 1, f"{path}: missing or ambiguous {name}")
                    actual = matches[0][0] or matches[0][1]
                    self.assertEqual(actual, expected, f"{path}: {name} drifted")

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

    def test_burn_then_remint_still_rejected_at_lifetime_cap(self):
        # Circulating supply can fall below cap after burns, but cumulative
        # issuance cannot exceed the fixed lifetime issuance ceiling.
        self.assertEqual(validate_supply(CAP_BASE_UNITS, 0, 100), CAP_BASE_UNITS - 100)
        with self.assertRaises(ValueError):
            validate_supply(CAP_BASE_UNITS, 100, 100)

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
