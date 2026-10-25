import unittest
import tempfile
import sys
from pathlib import Path

# GitHub Actions discovers this test from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent))
# The source may be absent from a sparse/filtered Actions working tree.
# Load the exact tracked version from HEAD, failing closed if it is not present.
import subprocess
import types
source = subprocess.run(
    ["git", "show", "HEAD:production-network/ops/prvi_genesis_preflight.py"],
    cwd=Path(__file__).resolve().parents[2],
    capture_output=True, text=True, check=True,
).stdout
preflight = types.ModuleType("privi_genesis_preflight")
exec(compile(source, "privi_genesis_preflight.py", "exec"), preflight.__dict__)
check, CAP = preflight.check, preflight.CAP

def genesis(amount):
    return {"app_state": {"bank": {"balances": [{"address": "test", "coins": [{"denom": "aprvi", "amount": str(amount)}]}], "supply": [{"denom": "aprvi", "amount": str(amount)}]}}}

class PreflightTests(unittest.TestCase):
    def test_at_cap(self):
        self.assertEqual(check(genesis(CAP))[0], [])
    def test_over_cap(self):
        self.assertTrue(check(genesis(CAP + 1))[0])
    def test_supply_mismatch(self):
        g = genesis(100)
        g["app_state"]["bank"]["supply"][0]["amount"] = "99"
        self.assertTrue(check(g)[0])
    def test_bad_amount(self):
        self.assertTrue(check(genesis("-1"))[0])
    def test_duplicate_account(self):
        g = genesis(100)
        g["app_state"]["bank"]["balances"].append(dict(g["app_state"]["bank"]["balances"][0]))
        self.assertIn("duplicate account address", check(g)[0])

    def test_duplicate_native_denom(self):
        g = genesis(100)
        g["app_state"]["bank"]["balances"][0]["coins"].append({"denom": "aprvi", "amount": "1"})
        self.assertIn("duplicate coin denom in account", check(g)[0])

    def test_noncanonical_leading_zero(self):
        self.assertIn("noncanonical native amount", check(genesis("0100"))[0])

    def test_duplicate_supply_denom(self):
        g = genesis(100)
        g["app_state"]["bank"]["supply"].append({"denom": "aprvi", "amount": "100"})
        self.assertIn("duplicate supply denom", check(g)[0])

    def test_zero_native_allocation(self):
        self.assertIn("no positive native PRVI allocation", check(genesis(0))[0])

    def test_malformed_app_state(self):
        self.assertIn("missing or malformed app_state", check({"app_state": []})[0])

    def test_malformed_account(self):
        g = genesis(100)
        g["app_state"]["bank"]["balances"] = [None]
        self.assertIn("malformed account or coin list", check(g)[0])

    def test_malformed_supply(self):
        g = genesis(100)
        g["app_state"]["bank"]["supply"] = [None]
        self.assertIn("malformed bank supply coin", check(g)[0])

    def test_native_denom_missing_from_balances(self):
        g = genesis(100)
        g["app_state"]["bank"]["balances"][0]["coins"][0]["denom"] = "other"
        self.assertIn("native PRVI denomination absent from balances", check(g)[0])

    def test_other_denom_supply_mismatch(self):
        g = genesis(100)
        g["app_state"]["bank"]["balances"][0]["coins"].append({"denom": "uatom", "amount": "5"})
        g["app_state"]["bank"]["supply"].append({"denom": "uatom", "amount": "6"})
        self.assertIn("bank supply differs from balances across denominations", check(g)[0])

    def test_matching_other_denom(self):
        g = genesis(100)
        g["app_state"]["bank"]["balances"][0]["coins"].append({"denom": "uatom", "amount": "5"})
        g["app_state"]["bank"]["supply"].append({"denom": "uatom", "amount": "5"})
        self.assertEqual(check(g)[0], [])

    def test_missing_balances(self):
        self.assertTrue(check({"app_state": {"bank": {"balances": [], "supply": [{"denom": "aprvi", "amount": "0"}]}}})[0])

    def test_extremely_large_amount_rejected_without_int_conversion(self):
        # Python 3.11+ limits decimal-to-int conversion; a malicious genesis
        # must yield a validation error rather than an uncaught ValueError.
        errors, _ = check(genesis("9" * 10000))
        self.assertIn("noncanonical native amount", errors)
        self.assertIn("noncanonical supply amount", errors)

    def test_extremely_large_other_denom_rejected(self):
        g = genesis(100)
        g["app_state"]["bank"]["balances"][0]["coins"].append(
            {"denom": "uatom", "amount": "7" * 5000})
        g["app_state"]["bank"]["supply"].append(
            {"denom": "uatom", "amount": "7" * 5000})
        errors, _ = check(g)
        self.assertIn("noncanonical coin amount", errors)
        self.assertIn("noncanonical supply amount", errors)

    def test_duplicate_json_keys_rejected_at_input(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "genesis.json"
            path.write_text('{"app_state":{"bank":{},"bank":{}}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate genesis JSON key"):
                preflight.load_genesis(path)

    def test_non_json_nan_is_rejected_at_input(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "genesis.json"
            path.write_text('{"app_state": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-JSON numeric constant"):
                preflight.load_genesis(path)

    def test_oversized_genesis_input_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "genesis.json"
            with path.open("wb") as stream:
                stream.truncate(preflight.MAX_GENESIS_FILE_BYTES + 1)
            with self.assertRaisesRegex(ValueError, "safety limit"):
                preflight.load_genesis(path)

if __name__ == "__main__":
    unittest.main()
