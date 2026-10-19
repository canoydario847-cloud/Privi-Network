"""Synthetic, zero-network chain identity observations. NOT mainnet evidence."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from verify_node_identity import verify

COSMOS="privi-test-stage-not-mainnet-1"
EVM=424242

def fixtures():
    comet={"jsonrpc":"2.0","id":1,"result":{
        "node_info":{"network":COSMOS},
        "sync_info":{"latest_block_height":"2","latest_block_hash":"a"*64,"catching_up":False}}}
    eth={"jsonrpc":"2.0","id":1,"result":hex(EVM)}
    return comet,eth

class IdentityReviewTests(unittest.TestCase):
    def test_exact_both_ids_pass_observation_only(self):
        c,e=fixtures()
        result=verify(c,e,COSMOS,EVM)
        self.assertEqual(result["observed_height"],2)
        self.assertEqual(result["financial_mainnet"],"NO_GO_REQUIRES_EXTERNAL_EVIDENCE")

    def test_cosmos_id_mismatch_fails(self):
        c,e=fixtures()
        c["result"]["node_info"]["network"]="local-4221"
        with self.assertRaisesRegex(ValueError,"Comet node chain ID"):
            verify(c,e,COSMOS,EVM)

    def test_evm_id_mismatch_fails(self):
        c,e=fixtures()
        e["result"]="0x38"
        with self.assertRaisesRegex(ValueError,"EVM chain ID"):
            verify(c,e,COSMOS,EVM)

    def test_refuse_pending_sync_or_insufficient_height(self):
        for catching in (True,None,"false",0):
            c,e=fixtures()
            c["result"]["sync_info"]["catching_up"]=catching
            with self.assertRaisesRegex(ValueError,"catching up"):
                verify(c,e,COSMOS,EVM)
        for height in ("0","1","02","-2","2e1",2,True,None):
            c,e=fixtures()
            c["result"]["sync_info"]["latest_block_height"]=height
            with self.assertRaises(ValueError,msg=str(height)):
                verify(c,e,COSMOS,EVM)

    def test_refuse_bad_block_hash(self):
        for value in (None,0,"a"*63,"g"*64,True):
            c,e=fixtures()
            c["result"]["sync_info"]["latest_block_hash"]=value
            with self.assertRaisesRegex(ValueError,"block hash"):
                verify(c,e,COSMOS,EVM)

    def test_refuse_non_hex_or_error_json_rpc(self):
        for data in ({"jsonrpc":"2.0","error":{"code":-1}},
                     {"result":424242},{"result":"424242"},
                     {"result":"0xnothex"},{"result":True}):
            c,_=fixtures()
            with self.assertRaises(ValueError,msg=str(data)):
                verify(c,data,COSMOS,EVM)

    def test_reject_non_uint64_expected_id(self):
        for value in (0,-1,True,"424242",2**64):
            c,e=fixtures()
            with self.assertRaisesRegex(ValueError,"positive uint64"):
                verify(c,e,COSMOS,value)

    def test_refuse_unreviewed_cosmos_identity(self):
        for ident in ("",None,"bad chain",True,"x"*81):
            c,e=fixtures()
            with self.assertRaisesRegex(ValueError,"reviewed"):
                verify(c,e,ident,EVM)

    def test_cli_remains_offline_and_redacts_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            c,e=fixtures()
            (root/"comet.json").write_text(json.dumps(c))
            (root/"eth.json").write_text(json.dumps(e))
            proc=subprocess.run([sys.executable,str(Path(__file__).with_name("verify_node_identity.py")),
                "--comet-status",str(root/"comet.json"),
                "--eth-chain-id",str(root/"eth.json"),
                "--expected-cosmos-id",COSMOS,
                "--expected-evm-id",str(EVM)],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr+proc.stdout)
            self.assertIn("NOT AN INDEPENDENT ATTESTATION",proc.stdout)
            self.assertIn("NO_GO_REQUIRES_EXTERNAL_EVIDENCE",proc.stdout)

if __name__=="__main__":
    unittest.main()
