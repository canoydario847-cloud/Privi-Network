"""Valueless synthetic genesis fixtures. No coin minting or cloud deployment."""
import copy
import importlib.util
import unittest
from pathlib import Path

p=Path(__file__).with_name("native_prvi_genesis_params.py")
spec=importlib.util.spec_from_file_location("native_prvi_genesis_params",p)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

def fixture():
    return {"chain_id":"privi-review-only-not-live-1",
            "app_state":{
                "bank":{
                    "supply":[{"denom":"aprvi","amount":"1000000000000000000"}],
                    "denom_metadata":[{
                        "base":"aprvi", "display":"PRVI", "symbol":"PRVI",
                        "denom_units":[{"denom":"aprvi","exponent":0},
                                       {"denom":"PRVI","exponent":18}]
                    }]
                },
                "evm":{"params":{"evm_denom":"aprvi"}},
                "staking":{"params":{"bond_denom":"aprvi"}},
                "mint":{
                    "params":{"mint_denom":"aprvi","inflation_rate_change":"0.000000000000000000",
                              "inflation_max":"0.000000000000000000",
                              "inflation_min":"0.000000000000000000"},
                    "minter":{"inflation":"0.000000000000000000",
                              "annual_provisions":"0.000000000000000000"}
                }
            }}

class NativeGenesisTest(unittest.TestCase):
    def test_valid_static_native_params(self):
        self.assertEqual(mod.audit(fixture())["native_prvi_parameters"],"PASS_STATIC_ONLY")
    def test_fee_denom_cannot_be_test(self):
        s=fixture();s["app_state"]["evm"]["params"]["evm_denom"]="atest"
        with self.assertRaisesRegex(ValueError,"EVM gas"):
            mod.audit(s)
    def test_staking_denom_cannot_be_stake(self):
        s=fixture();s["app_state"]["staking"]["params"]["bond_denom"]="stake"
        with self.assertRaisesRegex(ValueError,"staking bonded"):
            mod.audit(s)
    def test_mint_denom_cannot_diverge(self):
        s=fixture();s["app_state"]["mint"]["params"]["mint_denom"]="stake"
        with self.assertRaisesRegex(ValueError,"x/mint denomination"):
            mod.audit(s)
    def test_no_nonzero_inflation_schedule(self):
        for field in ("inflation_rate_change","inflation_max","inflation_min"):
            s=fixture();s["app_state"]["mint"]["params"][field]="0.000000000000000001"
            with self.assertRaisesRegex(ValueError,"zero"):
                mod.audit(s)
    def test_no_nonzero_minter_initial_state(self):
        for field in ("inflation","annual_provisions"):
            s=fixture();s["app_state"]["mint"]["minter"][field]="1"
            with self.assertRaisesRegex(ValueError,"zero"):
                mod.audit(s)
    def test_floats_and_scientific_format_disallowed(self):
        for value in (0,0.0,"0e9","NaN","","0.0.0","-0.0"):
            s=fixture();s["app_state"]["mint"]["minter"]["inflation"]=value
            with self.assertRaises(ValueError, msg=str(value)):
                mod.audit(s)
    def test_missing_module_refused(self):
        for module in ("bank","evm","staking","mint"):
            s=fixture();del s["app_state"][module]
            with self.assertRaises(ValueError, msg=module):
                mod.audit(s)
    def test_wrong_precision_refused(self):
        s=fixture();s["app_state"]["bank"]["denom_metadata"][0]["denom_units"][1]["exponent"]=6
        with self.assertRaisesRegex(ValueError,"18 decimals"):
            mod.audit(s)
    def test_duplicate_native_metadata_refused(self):
        s=fixture();s["app_state"]["bank"]["denom_metadata"].append(
            copy.deepcopy(s["app_state"]["bank"]["denom_metadata"][0]))
        with self.assertRaisesRegex(ValueError,"exactly one"):
            mod.audit(s)
    def test_wrong_symbol_refused(self):
        s=fixture();s["app_state"]["bank"]["denom_metadata"][0]["symbol"]="PRIV"
        with self.assertRaisesRegex(ValueError,"PRVI"):
            mod.audit(s)
    def test_native_supply_cap_boundary(self):
        s=fixture();s["app_state"]["bank"]["supply"][0]["amount"]=str(mod.MAX_BASE)
        self.assertEqual(mod.audit(s)["base_denom"],"aprvi")
        s["app_state"]["bank"]["supply"][0]["amount"]=str(mod.MAX_BASE+1)
        with self.assertRaisesRegex(ValueError,"exceeds"):
            mod.audit(s)
    def test_noncanonical_native_supply_refused(self):
        for amount in ("0","0001","-1","1e18",100,"",True):
            s=fixture();s["app_state"]["bank"]["supply"][0]["amount"]=amount
            with self.assertRaises(ValueError, msg=str(amount)):
                mod.audit(s)
    def test_broken_metadata_exponent_type(self):
        s=fixture();s["app_state"]["bank"]["denom_metadata"][0]["denom_units"][1]["exponent"]=True
        with self.assertRaisesRegex(ValueError,"integer"):
            mod.audit(s)

if __name__=="__main__":
    unittest.main()
