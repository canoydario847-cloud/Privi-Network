#!/usr/bin/env python3
"""Synthetic only read-only PRVI mainnet quorum monitor unit tests."""
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

src=Path(__file__).with_name("verify_live_consensus.py")
spec=importlib.util.spec_from_file_location("mainnet_monitor",src)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

EVM="https://evm.example.invalid/"
COMET="https://comet.example.invalid/"
CHAIN="privi-mainnet-999"
EVM_ID=999991
COUNT=4

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
            return {"result":{"signed_header":{"header":{"height":"100","chain_id":CHAIN},"commit":{"signatures":signatures}}}}
        raise AssertionError("unexpected Comet RPC URL: "+url)
    return fakepost,fakeget,validators,signatures

class MainnetQuorumMonitor(unittest.TestCase):
    def test_four_distinct_consensus_addresses_sign(self):
        p,g,_,_=make_responses()
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            result=m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)
        self.assertEqual("RPC_QUORUM_OBSERVED_ONLY",result["status"])
        self.assertFalse(result["financial_mainnet_authorized"])
        self.assertFalse(result["independent_operator_custody_verified"])
        self.assertEqual(4,result["validatorCount"])
        self.assertEqual(400,result["commitSignedVotingPower"])

    def test_demo_chain_rejected_without_rpc(self):
        with self.assertRaisesRegex(RuntimeError,"mainnet-only"):
            m.check(EVM,COMET,"local-4221",262144,now=1000)

    def test_remote_cleartext_rpc_rejected(self):
        with self.assertRaisesRegex(RuntimeError,"HTTPS"):
            m.check("http://network.example.invalid/",COMET,CHAIN,EVM_ID,now=1000)

    def test_missing_votes_blocks_health(self):
        p,g,validators,signatures=make_responses()
        for vote in signatures[2:]:
            vote["block_id_flag"]=1
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            with self.assertRaisesRegex(RuntimeError,"2/3 voting power"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)

    def test_few_validators_blocks_health(self):
        p,g,validators,signatures=make_responses()
        validators.pop();signatures.pop()
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            with self.assertRaisesRegex(RuntimeError,"at least four actual voting validators"):
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

    def test_mismatched_commit_height_denied(self):
        p,g,_,_=make_responses()
        def corrupt(url):
            answer=g(url)
            if "/commit?" in url:
                answer["result"]["signed_header"]["header"]["height"]="99"
            return answer
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",corrupt):
            with self.assertRaisesRegex(RuntimeError,"commit header height mismatch"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)

    def test_mismatched_commit_chain_denied(self):
        p,g,_,_=make_responses()
        def corrupt(url):
            answer=g(url)
            if "/commit?" in url:
                answer["result"]["signed_header"]["header"]["chain_id"]="privi-another"
            return answer
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",corrupt):
            with self.assertRaisesRegex(RuntimeError,"commit header chain ID mismatch"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)

    def test_duplicate_voting_address_denied(self):
        p,g,validators,_=make_responses()
        validators[1]["address"]=validators[0]["address"]
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            with self.assertRaisesRegex(RuntimeError,"Duplicate CometBFT"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)

    def test_unknown_vote_addresses_not_counted(self):
        p,g,_,signatures=make_responses()
        signatures[:]=[{"validator_address":"F"*40,"block_id_flag":2} for _ in range(4)]
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            with self.assertRaisesRegex(RuntimeError,"2/3 voting power"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)

    def test_two_of_four_votes_insufficient(self):
        p,g,_,signatures=make_responses()
        for sig in signatures[2:]:
            sig["block_id_flag"]=1
        with mock.patch.object(m,"post",p),mock.patch.object(m,"get",g):
            with self.assertRaisesRegex(RuntimeError,"2/3 voting power"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)

    def test_wrong_evm_id_denied(self):
        p,g,_,_=make_responses()
        def corrupt(url,method,params=None):
            if method=="eth_chainId": return "0x1"
            return p(url,method,params)
        with mock.patch.object(m,"post",corrupt),mock.patch.object(m,"get",g):
            with self.assertRaisesRegex(RuntimeError,"Wrong EVM chain"):
                m.check(EVM,COMET,CHAIN,EVM_ID,now=1000)

if __name__=="__main__": unittest.main()
