"""Tests for read-only EVM smoke checks; uses mock RPC, no real chain or funds."""
import importlib.util
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("privi_evm_smoke",Path(__file__).with_name("evm_smoke.py"))
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class StubRPC:
    def __init__(self,chain=7777,height=2):
        self.chain,self.height=chain,height
    def call(self,method,params=None):
        return {
            "eth_chainId":hex(self.chain),
            "eth_blockNumber":hex(self.height),
            "eth_getBlockByNumber":{"hash":"0x" + "1"*64},
        }[method]

class SmokeTests(unittest.TestCase):
    def test_reports_observed_and_expected_chain_id(self):
        with self.assertRaisesRegex(ValueError,r"expected 4221, observed 7777"):
            mod.check(StubRPC(),expected=4221)
    def test_matching_chain_and_block(self):
        outcome=mod.check(StubRPC(),expected=7777)
        self.assertEqual(outcome["chainId"],7777)
        self.assertEqual(outcome["blockHeight"],2)
    def test_refuses_eth_mainnet(self):
        with self.assertRaisesRegex(ValueError,"Unsafe/production"):
            mod.check(StubRPC(chain=1),expected=1)
    def test_refuses_unproduced_blocks(self):
        with self.assertRaisesRegex(ValueError,"No blocks"):
            mod.check(StubRPC(height=0),expected=7777)

if __name__=="__main__":
    unittest.main()
