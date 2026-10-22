import unittest
from privi_genesis_preflight import check, CAP

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

if __name__ == "__main__":
    unittest.main()
