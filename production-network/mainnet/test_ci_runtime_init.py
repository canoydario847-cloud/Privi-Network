#!/usr/bin/env python3
"""Synthetic, no-network tests of actual-initialized-genesis inspection."""
import copy
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("privi_ci_runtime",HERE/"ci_runtime_init.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def genesis():
    return {"chain_id":m.CID,"app_state":{
        "evm":{"params":{"evm_denom":"aprvi",
                         "extended_denom_options":{"extended_denom":"aprvi"}}},
        "staking":{"params":{"bond_denom":"aprvi"}},
        "mint":{"params":{"mint_denom":"aprvi"},
                "minter":{"inflation":"0.000000000000000000"}},
        "feemarket":{"params":{"no_base_fee":False}},
        "erc20":{"token_pairs":[]},
        "bank":{"supply":[]}
    }}


class InitInspectionTests(unittest.TestCase):
    def test_clean_unfunded_prvi_init_can_pass_synthetic_inspection(self):
        self.assertEqual(m.inspect(genesis()),[])

    def test_demo_gas_and_staking_denom_are_rejected(self):
        g=genesis()
        g["app_state"]["evm"]["params"]["evm_denom"]="atest"
        g["app_state"]["staking"]["params"]["bond_denom"]="stake"
        err=m.inspect(g)
        self.assertTrue(any("EVM native gas" in x for x in err))
        self.assertTrue(any("Staking bond denom" in x for x in err))

    def test_upstream_erc20_mint_and_fees_rejected(self):
        g=genesis()
        g["app_state"]["erc20"]["token_pairs"]=[{"contract":"demo"}]
        g["app_state"]["mint"]["minter"]["inflation"]="0.13"
        g["app_state"]["feemarket"]["params"]["no_base_fee"]=True
        err=m.inspect(g)
        self.assertGreaterEqual(len(err),3)

    def test_wrong_chain_id_and_overcap_rejected(self):
        g=genesis()
        g["chain_id"]="local-privi-seven-4221"
        g["app_state"]["bank"]["supply"]=[{"denom":"aprvi","amount":str(10**27+1)}]
        err=m.inspect(g)
        self.assertTrue(any("Cosmos ID" in x for x in err))
        self.assertTrue(any("supply exceeds" in x for x in err))

    def test_malformed_defaults_fail_closed(self):
        self.assertTrue(m.inspect({"chain_id":m.CID}))
        self.assertTrue(m.inspect({"chain_id":m.CID,"app_state":{"bank":{}}}))
        self.assertTrue(m.inspect("bad"))


if __name__=="__main__":
    unittest.main()
