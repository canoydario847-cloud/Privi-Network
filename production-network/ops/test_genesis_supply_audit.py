"""Synthetic fixtures only: verify initial PRVI supply accounting fails closed."""
import importlib.util
import unittest
from pathlib import Path

p=Path(__file__).with_name("genesis_supply_audit.py")
spec=importlib.util.spec_from_file_location("genesis_supply_audit",p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
UNIT=10**18

def fixture(amount=100*UNIT):
    return {"chain_id":"privi-candidate-1",
            "app_state":{"bank":{
                "balances":[{"address":"privi1example","coins":[{"denom":"aprvi","amount":str(amount)}]}],
                "supply":[{"denom":"aprvi","amount":str(amount)}]}}}

class SupplyAuditTests(unittest.TestCase):
    def check(self,g):return mod.audit(g,"aprvi","privi-candidate-1")
    def test_valid_allocation(self):
        self.assertEqual(self.check(fixture())["genesis_bank_audit"],"PASS")
    def test_cap_breach(self):
        with self.assertRaisesRegex(ValueError,"exceeds"):
            self.check(fixture(mod.CAP_BASE+1))
    def test_supply_balance_mismatch(self):
        g=fixture()
        g["app_state"]["bank"]["supply"][0]["amount"]="1"
        with self.assertRaisesRegex(ValueError,"differs"):
            self.check(g)
    def test_unexpected_chain(self):
        with self.assertRaisesRegex(ValueError,"chain_id"):
            self.check({"chain_id":"another-network","app_state":fixture()["app_state"]})
    def test_negative_amount(self):
        with self.assertRaisesRegex(ValueError,"nonnegative"):
            self.check(fixture(-1))
    def test_duplicate_account(self):
        g=fixture()
        g["app_state"]["bank"]["balances"].append(g["app_state"]["bank"]["balances"][0].copy())
        with self.assertRaisesRegex(ValueError,"duplicate bank address"):
            self.check(g)
    def test_missing_supply(self):
        g=fixture()
        g["app_state"]["bank"]["supply"]=[]
        with self.assertRaisesRegex(ValueError,"missing"):
            self.check(g)
    def test_zero_rejected(self):
        with self.assertRaisesRegex(ValueError,"zero"):
            self.check(fixture(0))
    def test_invalid_genesis_state(self):
        with self.assertRaises((ValueError,AttributeError)):
            self.check({"chain_id":"privi-candidate-1","app_state":None})

if __name__=="__main__": unittest.main()
