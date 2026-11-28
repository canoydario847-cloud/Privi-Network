import unittest
from types import SimpleNamespace
from unittest.mock import patch
import check_rpc_identity as rpc

class TestRPCIdentity(unittest.TestCase):
    def setUp(self):
        self.args=SimpleNamespace(comet="https://comet.example",evm="https://evm.example",cosmos_id="candidate-1",evm_id=262144)
        self.status={"result":{"node_info":{"network":"candidate-1"},"sync_info":{"catching_up":False,"latest_block_height":"100"}}}

    def check(self, results):
        with patch.object(rpc,"request",return_value=self.status),patch.object(rpc,"evm",side_effect=results):
            return rpc.sample(self.args)

    def test_matching(self):
        self.assertEqual(self.check([False,hex(262144),hex(100)]),(100,100))

    def test_wrong_evm(self):
        with self.assertRaisesRegex(ValueError,"Unexpected EVM"):
            self.check([False,hex(772626)])

    def test_wrong_cosmos(self):
        self.status["result"]["node_info"]["network"]="privi-devnet-1"
        with self.assertRaisesRegex(ValueError,"Unexpected Cosmos"):
            self.check([])

    def test_syncing(self):
        with self.assertRaisesRegex(ValueError,"synchronizing"):
            self.check([{"currentBlock":"0x1"}])

    def test_height_mismatch(self):
        with self.assertRaisesRegex(ValueError,"inconsistent"):
            self.check([False,hex(262144),hex(10)])

if __name__ == "__main__":
    unittest.main()
