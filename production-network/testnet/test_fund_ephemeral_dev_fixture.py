import importlib.util
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("dev_fixture",Path(__file__).with_name("fund_ephemeral_dev_fixture.py"))
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
ADDR="cosmos1"+"a"*38

def genesis():
    return {"chain_id":"local-4221","app_state":{"bank":{
       "balances":[{"address":ADDR,"coins":[{"denom":"atest","amount":"10000"}]},
                   {"address":"cosmos1"+"b"*38,"coins":[{"denom":"atest","amount":"100"}]}],
       "supply":[{"denom":"atest","amount":"10100"}]}}}

class FixtureFundingTests(unittest.TestCase):
    def test_funds_dev_without_silent_minting_discrepancy(self):
        out=mod.update_genesis(genesis(),ADDR)
        bank=out["app_state"]["bank"]
        self.assertEqual(int(bank["balances"][0]["coins"][0]["amount"]),mod.ADDED_WEI+10000)
        self.assertEqual(int(bank["supply"][0]["amount"]),mod.ADDED_WEI+10100)
    def test_rejects_non_demo_chain(self):
        g=genesis();g["chain_id"]="privi-mainnet"
        with self.assertRaisesRegex(ValueError,"non-local"):
            mod.update_genesis(g,ADDR)
    def test_refuses_repeat_funding(self):
        once=mod.update_genesis(genesis(),ADDR)
        with self.assertRaisesRegex(ValueError,"double top-up"):
            mod.update_genesis(once,ADDR)
    def test_refuses_unbalanced_input(self):
        g=genesis();g["app_state"]["bank"]["supply"][0]["amount"]="1"
        with self.assertRaisesRegex(ValueError,"does not balance"):
            mod.update_genesis(g,ADDR)
    def test_refuses_unknown_account(self):
        with self.assertRaisesRegex(ValueError,"absent"):
            mod.update_genesis(genesis(),"cosmos1"+"c"*38)

if __name__=="__main__":unittest.main()
