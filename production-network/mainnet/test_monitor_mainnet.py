#!/usr/bin/env python3
"""Synthetic only read-only PRVI mainnet quorum monitor unit tests."""
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

src=Path(__file__).with_name("monitor_mainnet.py")
spec=importlib.util.spec_from_file_location("mainnet_monitor",src)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

EVM="https://evm.example.invalid/"
COMET="https://comet.example.invalid/"
CHAIN="privi-mainnet-999"
EVM_ID=999991
COUNT=7

def make_responses():
    validators=[{"address":f"{i:040X}","voting_power":"100"} for i in range(COUNT)]
    signatures=[{"validator_address":x["address"],"block_id_flag":2} for x in validators]
    def fakepost(url,method,params=None):
        if method=="eth_chainId":return hex(EVM_ID)
        if method=="eth_blockNumber":return hex(100)
        if method=="eth_getBlockByNumber":
            return {"hash":"0x"+("ab"*32),"timestamp":hex(990)}
        raise AssertionError("unexpected Ethereum method: "+method)
    def fakeget(url):
        if url.endswith("/status"):
            return {"result":{"node_info":{"network":CHAIN},
                    "sync_info":{"catching_up":False,"latest_block_height":"100"}}}
        if "/validators?" in url:
            return {"result":{"total":str(len(validators)),"validators":validators}}
        if "/commit?" in url:
            return {"result":{"signed_header":{"commit":{"signatures":signatures}}}}
        raise AssertionError("unexpected Comet RPC URL: "+url)
    return fakepost,fakeget,validators,signatures

class MainnetQuorumMonitor(unittest.TestCase):
    def test_all_seven_independent_power_addresses_sign(self):
        p,g,_,_=make_responses()
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            result=m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)
        self.assertEqual("PASS",result["status"])
        self.assertEqual(7,result["validatorCount"])
        self.assertEqual(700,result["commitSignedVotingPower"])

    def test_demo_chain_rejected_without_rpc(self):
        with self.assertRaisesRegex(RuntimeError,"mainnet-only"):
            m.check(EVM,COMET,"local-4221",262144,now=1000)

    def test_remote_cleartext_rpc_rejected(self):
        with self.assertRaisesRegex(RuntimeError,"HTTPS"):
            m.check("http://network.example.invalid/",COMET,CHAIN,EVM_ID,now=1000)

    def test_missing_votes_blocks_health(self):
        p,g,validators,signatures=make_responses()
        for vote in signatures[4:]:
            vote["block_id_flag"]=1
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            with self.assertRaisesRegex(RuntimeError,"2/3 voting power"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)

    def test_few_validators_blocks_health(self):
        p,g,validators,signatures=make_responses()
        validators.pop();signatures.pop()
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            with self.assertRaisesRegex(RuntimeError,"7\\+ voting-validator"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)

    def test_stale_block_blocks_health(self):
        p,g,_,_=make_responses()
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            with self.assertRaisesRegex(RuntimeError,"stale"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=5000)

    def test_vote_concentration_blocks_health(self):
        p,g,validators,_=make_responses()
        validators[0]["voting_power"]="400"
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            with self.assertRaisesRegex(RuntimeError,"1/3"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)

if __name__=="__main__": unittest.main()
