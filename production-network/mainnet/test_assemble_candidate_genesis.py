#!/usr/bin/env python3
"""Offline synthetic tests only; never create real accounts, balances or signing keys."""
import copy
import importlib.util
import json
import unittest
from pathlib import Path

HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location("privi_candidate_assembler",HERE/"assemble_candidate_genesis.py")
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
config=json.loads((HERE/"privi_chain_config.json").read_text())

def fake_bech32_20byte_address(index):
    """Encode SYNTHETIC 20-byte fixtures, no private keys."""
    payload=bytes([index])*20
    words=[]; acc=0;bits=0
    for byte in payload:
        acc=(acc<<8)|byte;bits+=8
        while bits>=5:
            bits-=5
            words.append((acc>>bits)&31)
    if bits:words.append((acc<<(5-bits))&31)
    hrp="privi"
    initial=[ord(c)>>5 for c in hrp]+[0]+[ord(c)&31 for c in hrp]
    residue=a.bech32_polymod(initial+words+[0]*6)^1
    check=[(residue>>(5*(5-i)))&31 for i in range(6)]
    return "privi1"+"".join(a.BECH32_CHARS[i] for i in words+check)

def fixture():
    cfg=copy.deepcopy(config)
    cfg["network"]["cosmos_chain_id"]="privi-mainnet-999"
    cfg["network"]["evm_chain_id"]=999991
    template={"chain_id":"","validators":[],"app_state":{
        "auth":{"accounts":[]},"bank":{"balances":[],"supply":[],"denom_metadata":[]},
        "staking":{"params":{}},
        "slashing":{"params":{}},
        "mint":{"params":{},"minter":{}},
        "erc20":{"token_pairs":[]},
        "evm":{"params":{}},
        "feemarket":{"params":{}},
        "genutil":{"gen_txs":[]}
    }}
    entries=[]
    for i,policy in enumerate(cfg["allocations_policy"]):
        row={
          "address":fake_bech32_20byte_address(i+1),
          "category":policy["name"],
          "amount_base_units":policy["amount_base_units"]
        }
        if policy["name"] in a.PROTECTED:
            row["vesting_start_unix"]="1900000000"
            row["vesting_periods"]=[{
              "length_seconds":"31536000",
              "amount_base_units":policy["amount_base_units"]
            }]
        entries.append(row)
    return template,{"allocations":entries},cfg

class OfflineGenesisAssembler(unittest.TestCase):
    def test_bech32_checksum_required(self):
        address=fake_bech32_20byte_address(1)
        self.assertTrue(a.valid_privi_account(address))
        self.assertFalse(a.valid_privi_account(address[:-1]+("q" if address[-1]!="q" else "p")))
        self.assertFalse(a.valid_privi_account("privi1"+("q"*38)))

    def test_valid_synthetic_candidate_is_still_not_authorized_genesis(self):
        t,l,c=fixture()
        result=a.assemble(t,l,c,1900000000)
        self.assertEqual(c["network"]["cosmos_chain_id"],result["chain_id"])
        self.assertEqual([] ,result["app_state"]["genutil"]["gen_txs"])
        self.assertEqual(str(a.CAP),result["app_state"]["bank"]["supply"][0]["amount"])
        self.assertEqual(5,len(result["app_state"]["auth"]["accounts"]))
        self.assertEqual("aprvi",result["app_state"]["staking"]["params"]["bond_denom"])

    def test_missing_real_chain_ids_refuses_genesis(self):
        t,l,c=fixture()
        c["network"]["cosmos_chain_id"]=None
        with self.assertRaises(a.NotReady):a.assemble(t,l,c,1900000000)

    def test_cannot_overwrite_preexisting_testnet_balances(self):
        t,l,c=fixture()
        t["app_state"]["bank"]["balances"]=[{"address":"old-test-wallet"}]
        with self.assertRaisesRegex(a.NotReady,"existing|accounts/supply"):
            a.assemble(t,l,c,1900000000)

    def test_overallocation_rejected(self):
        t,l,c=fixture()
        l["allocations"][0]["amount_base_units"]=str(a.CATEGORIES["community_adoption"]+1)
        with self.assertRaises(a.NotReady):a.assemble(t,l,c,1900000000)

    def test_missing_onchain_vesting_rejected(self):
        t,l,c=fixture()
        for row in l["allocations"]:
            if row["category"]=="contributors":del row["vesting_periods"]
        with self.assertRaisesRegex(a.NotReady,"vesting"):
            a.assemble(t,l,c,1900000000)

    def test_duplicate_address_rejected(self):
        t,l,c=fixture()
        l["allocations"][0]["address"]=l["allocations"][1]["address"]
        with self.assertRaisesRegex(a.NotReady,"Repeated"):
            a.assemble(t,l,c,1900000000)

    def test_no_genesis_without_complete_module_template(self):
        t,l,c=fixture()
        del t["app_state"]["staking"]
        with self.assertRaisesRegex(a.NotReady,"complete"):
            a.assemble(t,l,c,1900000000)

if __name__=="__main__":unittest.main()
