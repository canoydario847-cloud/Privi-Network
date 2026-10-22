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
    def test_missing_balances(self):
        self.assertTrue(check({"app_state": {"bank": {"balances": [], "supply": [{"denom": "aprvi", "amount": "0"}]}}})[0])

if __name__ == "__main__":
    unittest.main()
