"""Safe, mocked RPC unit tests; no real wallet, keys or tokens required."""
import importlib.util
import sys
import unittest
from pathlib import Path

here=Path(__file__).resolve().parent
sys.path.insert(0,str(here))
spec=importlib.util.spec_from_file_location("wallet_rpc_smoke",here/"wallet_rpc_smoke.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeRPC:
    def __init__(self):
        self.calls=[]
        self.values={
            "eth_chainId":"0x40000",
            "eth_blockNumber":"0x4",
            "eth_getBlockByNumber":{"number":"0x4","hash":"0x"+"a"*64},
            "eth_getBalance":"0x0",
            "eth_getTransactionCount":"0x0",
            "eth_getCode":"0x",
            "eth_gasPrice":"0x1",
        }
    def call(self, method, params=None):
        self.calls.append((method,params))
        return self.values[method]


class WalletRPCSmokeTests(unittest.TestCase):
    def setUp(self):self.rpc=FakeRPC()
    def test_passes_standard_queries(self):
        result=mod.check(self.rpc,262144)
        self.assertEqual(result["status"],"READ_ONLY_WALLET_RPC_CHECKS_PASSED")
        self.assertEqual(result["probe_balance_wei"],"0")
        self.assertEqual(result["probe_transaction_count"],0)
        self.assertEqual(self.rpc.calls[-1][0],"eth_gasPrice")
        self.assertEqual(self.rpc.calls[3][1][1],"0x4")
        self.assertEqual(self.rpc.calls[4][1][1],"0x4")
        self.assertEqual(self.rpc.calls[5][1][1],"0x4")
    def test_rejects_wrong_chain(self):
        with self.assertRaisesRegex(ValueError,"chain ID mismatch"):
            mod.check(self.rpc,12345)
    def test_rejects_production_chain_ids_without_any_rpc(self):
        with self.assertRaisesRegex(ValueError,"refusing"):
            mod.check(self.rpc,1)
        self.assertEqual(self.rpc.calls,[])
    def test_rejects_non_hex_balances(self):
        self.rpc.values["eth_getBalance"]="10"
        with self.assertRaisesRegex(ValueError,"eth_getBalance"):
            mod.check(self.rpc,262144)
    def test_rejects_odd_length_code(self):
        self.rpc.values["eth_getCode"]="0xabc"
        with self.assertRaisesRegex(ValueError,"eth_getCode"):
            mod.check(self.rpc,262144)
    def test_rejects_unavailable_block_history(self):
        self.rpc.values["eth_getBlockByNumber"]=None
        with self.assertRaisesRegex(ValueError,"hash unavailable"):
            mod.check(self.rpc,262144)
    def test_rejects_inconsistent_block_number(self):
        self.rpc.values["eth_getBlockByNumber"]["number"]="0x3"
        with self.assertRaisesRegex(ValueError,"number mismatch"):
            mod.check(self.rpc,262144)
    def test_rejects_invalid_address_before_rpc(self):
        with self.assertRaisesRegex(ValueError,"probe address"):
            mod.check(self.rpc,262144,address="0xdead")
        self.assertEqual(self.rpc.calls,[])
    def test_rejects_noncanonical_zero_quantity(self):
        self.rpc.values["eth_gasPrice"]="0x00"
        with self.assertRaisesRegex(ValueError,"eth_gasPrice"):
            mod.check(self.rpc,262144)


if __name__=="__main__":
    unittest.main()
