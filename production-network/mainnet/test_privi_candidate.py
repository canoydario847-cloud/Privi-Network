#!/usr/bin/env python3
"""Unit tests do NOT generate usable mainnet wallets or release genesis."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path
from test_bech32_accounts import test_address

ROOT=Path(__file__).parent

def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+".py"))
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

gen=module("validate_candidate_genesis")
overlay=module("privi_source_overlay")
cfg=json.loads((ROOT/"privi_chain_config.json").read_text())

def demo_genesis():
    d=copy.deepcopy(cfg)
    d["network"]["cosmos_chain_id"]="privi-mainnet-999"
    d["network"]["evm_chain_id"]=999991
    cats=gen.CATEGORIES
    ledger=[]
    bank=[]
    accounts=[]
    for i,(category,amount) in enumerate(cats.items()):
        # Synthetic checksum-valid fixture identifiers, NOT owned accounts or keys.
        addr=test_address(i)
        ledger.append({"address":addr,"category":category,"amount_base_units":str(amount)})
        bank.append({"address":addr,"coins":[{"denom":"aprvi","amount":str(amount)}]})
        if category in ("contributors","protocol_treasury","ecosystem_development"):
            period={"length":"31536000","amount":[{"denom":"aprvi","amount":str(amount)}]}
            accounts.append({
              "@type":"/cosmos.vesting.v1beta1.PeriodicVestingAccount",
              "base_vesting_account":{
                "base_account":{"address":addr},"original_vesting":[{"denom":"aprvi","amount":str(amount)}],
                "delegated_free":[],"delegated_vesting":[],"end_time":"3185136000"
              },"start_time":"3153600000","vesting_periods":[period]})
        else:
            accounts.append({"@type":"/cosmos.auth.v1beta1.BaseAccount","address":addr})
    state={
       "bank":{"supply":[{"denom":"aprvi","amount":str(gen.CAP)}],
               "balances":bank,"denom_metadata":[{"base":"aprvi","display":"prvi",
                 "denom_units":[{"denom":"aprvi","exponent":0},{"denom":"prvi","exponent":18}]}]},
       "auth":{"accounts":accounts},
       "staking":{"params":{"bond_denom":"aprvi","unbonding_time":"1814400s",
                              "max_validators":100,"min_commission_rate":"0.05"}},
       "slashing":{"params":{"slash_fraction_double_sign":"0.05","slash_fraction_downtime":"0.0001"}},
       "evm":{"params":{"evm_denom":"aprvi","extended_denom_options":{"extended_denom":"aprvi"}}},
       "mint":{"params":{"mint_denom":"aprvi"},"minter":{"inflation":"0.000000000000000000"}},
       "erc20":{"token_pairs":[]},
       "feemarket":{"params":{"no_base_fee":False}}
    }
    return {"chain_id":"privi-mainnet-999","app_state":state},{"allocations":ledger},d

class CandidateGenesisTest(unittest.TestCase):
    def test_reference_fixture_valid_only_structurally(self):
        doc,alloc,c=demo_genesis()
        self.assertEqual([],gen.errors_for(doc,alloc,c))

    def test_extra_genesis_supply_rejected(self):
        doc,alloc,c=demo_genesis()
        doc["app_state"]["bank"]["supply"][0]["amount"]=str(gen.CAP+1)
        errs=gen.errors_for(doc,alloc,c)
        self.assertTrue(any("Bank native supply" in e for e in errs),errs)

    def test_vesting_does_not_match(self):
        doc,alloc,c=demo_genesis()
        doc["app_state"]["auth"]["accounts"][1]["vesting_periods"][0]["amount"][0]["amount"]="1"
        errs=gen.errors_for(doc,alloc,c)
        self.assertTrue(any("Vesting sum" in e for e in errs),errs)

    def test_testnet_coin_prohibited(self):
        doc,alloc,c=demo_genesis()
        doc["app_state"]["bank"]["supply"].append({"denom":"atest","amount":"100"})
        errs=gen.errors_for(doc,alloc,c)
        self.assertTrue(any("Unexpected coin denomination" in e for e in errs),errs)

    def test_wrong_staking_denom_rejected(self):
        doc,alloc,c=demo_genesis()
        doc["app_state"]["staking"]["params"]["bond_denom"]="atest"
        errs=gen.errors_for(doc,alloc,c)
        self.assertTrue(any("bond denom" in e for e in errs),errs)

    def test_inflation_not_allowed(self):
        doc,alloc,c=demo_genesis()
        doc["app_state"]["mint"]["minter"]["inflation"]="0.1"
        errs=gen.errors_for(doc,alloc,c)
        self.assertTrue(any("inflation" in e for e in errs),errs)

    def test_erc20_demo_pair_prohibited(self):
        doc,alloc,c=demo_genesis()
        doc["app_state"]["erc20"]["token_pairs"]=[{"erc20_address":"0xabcd"}]
        self.assertTrue(any("demo ERC20" in e for e in gen.errors_for(doc,alloc,c)))

    def test_no_base_fee_prohibited(self):
        doc,alloc,c=demo_genesis()
        doc["app_state"]["feemarket"]["params"]["no_base_fee"]=True
        self.assertTrue(any("fee market" in e for e in gen.errors_for(doc,alloc,c)))

class SourceOverlayTest(unittest.TestCase):
    def test_unapproved_default_chain_ids_blocked(self):
        with self.assertRaises(overlay.UnsafeInput):
            overlay.validated_settings(cfg)
        cloned=copy.deepcopy(cfg)
        cloned["network"]["cosmos_chain_id"]="privi-mainnet-999"
        cloned["network"]["evm_chain_id"]=262144
        with self.assertRaises(overlay.UnsafeInput):
            overlay.validated_settings(cloned)

    def test_unique_mainnet_ids_accepted_for_drafting(self):
        cloned=copy.deepcopy(cfg)
        cloned["network"]["cosmos_chain_id"]="privi-mainnet-999"
        cloned["network"]["evm_chain_id"]=999991
        self.assertEqual(("privi-mainnet-999",999991),
                         overlay.validated_settings(cloned))

    def test_source_overlay_rejects_drift(self):
        with self.assertRaises(overlay.UnsafeInput):
            overlay.source_overlay({
                "evmd/config/bech32.go":'Bech32Prefix = "changed"',
                "evmd/genesis.go":"foo",
                "evmd/cmd/evmd/cmd/root.go":"foo",
                "evmd/app.go":"foo",
            },999991)

if __name__=="__main__":
    unittest.main()
