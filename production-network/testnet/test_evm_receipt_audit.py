"""Mock only; these tests do not send transactions or use real funds."""
import importlib.util
import sys
import unittest
from pathlib import Path
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here))
spec=importlib.util.spec_from_file_location("evm_receipt_audit",here/"evm_receipt_audit.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

HASH="0x"+"1"*64
BHASH="0x"+"2"*64
FROM="0x"+"a"*40
TO="0x"+"b"*40

class FakeRPC:
    def __init__(self):
        self.values={
          "eth_chainId":"0x40000",
          "eth_getTransactionByHash":{"hash":HASH,"from":FROM,"to":TO,"value":"0x64","input":"0x","blockHash":BHASH,"blockNumber":"0x8","chainId":"0x40000","gas":"0x7530","gasPrice":"0x3b9aca00"},
          "eth_getTransactionReceipt":{"transactionHash":HASH,"status":"0x1","blockNumber":"0x8","blockHash":BHASH,"gasUsed":"0x5208","effectiveGasPrice":"0x3b9aca00"},
          "eth_blockNumber":"0x9",
          "eth_getBlockByNumber":{"hash":BHASH,"transactions":[HASH]}
        }
    def call(self,method,params=None):
        if method=="eth_getBlockByNumber" and params==["0x0",False]:
            return {"hash":"0x"+"5"*64}
        return self.values[method]

class EVMReceiptTests(unittest.TestCase):
    def setUp(self):self.rpc=FakeRPC()
    def verify(self,confirmations=2):
        return mod.check(self.rpc,HASH,262144,FROM,TO,100,confirmations)
    def test_valid_native_receipt(self):
        out=self.verify()
        self.assertEqual(out["confirmations"],2)
        self.assertIs(out["execution_succeeded"],True)
        self.assertEqual(out["genesis_hash"],"0x"+"5"*64)
        self.assertEqual(out["evm_chain_id"],262144)
        self.assertEqual(out["gas_used"],"21000")
        self.assertEqual(out["effective_gas_price_wei"],"1000000000")
        self.assertEqual(out["gross_gas_paid_wei"],"21000000000000")
    def test_gas_used_must_not_exceed_signed_gas_limit(self):
        self.rpc.values["eth_getTransactionReceipt"]["gasUsed"]="0x7531"
        with self.assertRaisesRegex(ValueError,"invalid EVM gas usage"):
            self.verify()
    def test_effective_price_must_not_exceed_signed_legacy_price(self):
        self.rpc.values["eth_getTransactionReceipt"]["effectiveGasPrice"]="0x3b9aca01"
        with self.assertRaisesRegex(ValueError,"exceeds transaction gas price"):
            self.verify()
    def test_gas_price_must_not_be_zero(self):
        self.rpc.values["eth_getTransactionByHash"]["gasPrice"]="0x0"
        with self.assertRaisesRegex(ValueError,"exceeds transaction gas price"):
            self.verify()
    def test_missing_gas_fields_fail_closed(self):
        self.rpc.values["eth_getTransactionReceipt"].pop("gasUsed")
        with self.assertRaisesRegex(ValueError,"receipt gasUsed"):
            self.verify()
    def test_invalid_effective_gas_price_fails_closed(self):
        self.rpc.values["eth_getTransactionReceipt"]["effectiveGasPrice"]="1.5"
        with self.assertRaisesRegex(ValueError,"receipt effectiveGasPrice"):
            self.verify()
    def test_missing_or_malformed_genesis_hash_fails_closed(self):
        for genesis in (None, {}, {"hash":"invalid"}):
            with self.subTest(genesis=genesis):
                original=self.rpc.call
                def mock_call(method,params=None):
                    if method=="eth_getBlockByNumber" and params==["0x0",False]:
                        return genesis
                    return original(method,params)
                self.rpc.call=mock_call
                try:
                    with self.assertRaisesRegex(ValueError,"genesis block hash"):
                        self.verify()
                finally:
                    self.rpc.call=original
    def test_transaction_receipt_height_disagreement(self):
        self.rpc.values["eth_getTransactionByHash"]["blockNumber"]="0x7"
        with self.assertRaisesRegex(ValueError,"block height disagreement"):
            self.verify()
    def test_missing_transaction_block_height(self):
        self.rpc.values["eth_getTransactionByHash"].pop("blockNumber")
        with self.assertRaisesRegex(ValueError,"transaction blockNumber"):
            self.verify()
    def test_wrong_network(self):
        with self.assertRaisesRegex(ValueError,"EVM chain ID mismatch"):
            mod.check(self.rpc,HASH,4221,FROM,TO,100)
    def test_failed_receipt(self):
        self.rpc.values["eth_getTransactionReceipt"]["status"]="0x0"
        with self.assertRaisesRegex(ValueError,"failed"):
            self.verify()
    def test_too_few_confirmations(self):
        with self.assertRaisesRegex(ValueError,"insufficient"):
            self.verify(3)
    def test_different_block(self):
        self.rpc.values["eth_getBlockByNumber"]["hash"]="0x"+"4"*64
        with self.assertRaisesRegex(ValueError,"block hash disagreement"):
            self.verify()
    def test_wrong_value(self):
        with self.assertRaisesRegex(ValueError,"amount"):
            mod.check(self.rpc,HASH,262144,FROM,TO,200)
    def test_contract_calldata_rejected(self):
        self.rpc.values["eth_getTransactionByHash"]["input"]="0x1234"
        with self.assertRaisesRegex(ValueError,"nonempty calldata"):
            self.verify()
    def test_missing_receipt(self):
        self.rpc.values["eth_getTransactionReceipt"]=None
        with self.assertRaisesRegex(ValueError,"receipt missing"):
            self.verify()

if __name__=="__main__":unittest.main()
