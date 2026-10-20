"""Synthetic four-node Comet/EVM observations; no host or network access."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from verify_four_validator_observations import verify

CHAIN = "privi-stage-not-financial-1"
EVM = 424242

def fixture(root):
    bundle = {
        "schema_version": 1,
        "purpose": "valueless-four-host-staging",
        "cosmos_chain_id": CHAIN,
        "evm_chain_id": EVM,
        "nodes": [],
    }
    for i in range(1, 5):
        c = {
            "jsonrpc": "2.0", "id": 1,
            "result": {
                "node_info": {"network": CHAIN, "id": f"{i:040x}"},
                "sync_info": {
                    "latest_block_height": "21",
                    "latest_block_hash": "a" * 64,
                    "catching_up": False,
                },
                "validator_info": {
                    "address": f"{i+100:040x}", "voting_power": "1",
                },
            },
        }
        e = {"jsonrpc":"2.0","id":1,"result":hex(EVM)}
        name = f"privi-owner-val-{i:02d}"
        c_file, e_file = f"node{i}-comet.json", f"node{i}-eth.json"
        (root/c_file).write_text(json.dumps(c),encoding="utf-8")
        (root/e_file).write_text(json.dumps(e),encoding="utf-8")
        bundle["nodes"].append({
            "id": name, "comet_status":c_file,"eth_chain_id":e_file,
        })
    return bundle

class FourNodeObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.bundle=fixture(self.base)

    def modify_comet(self,i,fn):
        path=self.base/self.bundle["nodes"][i]["comet_status"]
        data=json.loads(path.read_text())
        fn(data)
        path.write_text(json.dumps(data),encoding="utf-8")

    def modify_eth(self,i,fn):
        path=self.base/self.bundle["nodes"][i]["eth_chain_id"]
        data=json.loads(path.read_text())
        fn(data)
        path.write_text(json.dumps(data),encoding="utf-8")

    def test_four_distinct_nodes_same_block_match_observation_only(self):
        report=verify(self.bundle,self.base)
        self.assertEqual(report["observation"],"FOUR_UNAUTHENTICATED_SNAPSHOTS_CONCUR")
        self.assertEqual(report["observed_height"],21)
        self.assertEqual(report["distinct_comet_peers"],4)
        self.assertEqual(report["distinct_validator_addresses"],4)
        self.assertIn("NO_GO",report["financial_mainnet"])

    def test_wrong_ethereum_chain_id_rejected(self):
        self.modify_eth(2,lambda doc: doc.update(result="0x1"))
        with self.assertRaisesRegex(ValueError,"EVM chain ID"):
            verify(self.bundle,self.base)

    def test_wrong_cosmos_network_rejected(self):
        self.modify_comet(1,lambda doc: doc["result"]["node_info"].update(network="local-4221"))
        with self.assertRaisesRegex(ValueError,"Comet node chain ID"):
            verify(self.bundle,self.base)

    def test_different_heights_not_equivalent(self):
        self.modify_comet(1,lambda doc: doc["result"]["sync_info"].update(latest_block_height="22"))
        with self.assertRaisesRegex(ValueError,"different heights"):
            verify(self.bundle,self.base)

    def test_same_height_different_hash_is_rejected(self):
        self.modify_comet(0,lambda doc: doc["result"]["sync_info"].update(latest_block_hash="f"*64))
        with self.assertRaisesRegex(ValueError,"disagree on block hash"):
            verify(self.bundle,self.base)

    def test_duplicate_comet_peer_is_rejected(self):
        self.modify_comet(3,lambda doc: doc["result"]["node_info"].update(id=f"{1:040x}"))
        with self.assertRaisesRegex(ValueError,"duplicate peer ID"):
            verify(self.bundle,self.base)

    def test_duplicate_validator_address_is_rejected(self):
        self.modify_comet(2,lambda doc: doc["result"]["validator_info"].update(address=f"{101:040x}"))
        with self.assertRaisesRegex(ValueError,"duplicate peer ID or validator"):
            verify(self.bundle,self.base)

    def test_non_validator_zero_power_is_rejected(self):
        for power in ("0","00",0,True,"-1","1e6"):
            self.modify_comet(0,lambda doc: doc["result"]["validator_info"].update(voting_power=power))
            with self.assertRaisesRegex(ValueError,"positive integer voting power"):
                verify(self.bundle,self.base)

    def test_catching_up_node_is_rejected(self):
        self.modify_comet(0,lambda doc: doc["result"]["sync_info"].update(catching_up=True))
        with self.assertRaisesRegex(ValueError,"catching up"):
            verify(self.bundle,self.base)

    def test_bad_id_and_wrong_count_fail_without_type_error(self):
        for bad in (None,[],{},True,22,["privi-owner-val-01"]):
            bundle=copy.deepcopy(self.bundle)
            bundle["nodes"][0]["id"]=bad
            with self.assertRaisesRegex(ValueError,"unique, exact"):
                verify(bundle,self.base)
        for count in (0,3,5):
            bundle=copy.deepcopy(self.bundle)
            bundle["nodes"]=bundle["nodes"][:count]+(
                [bundle["nodes"][-1]] if count==5 else [])
            with self.assertRaises(ValueError):
                verify(bundle,self.base)

    def test_duplicate_snapshots_and_invalid_names_fail(self):
        for name in ("../escape.json","/tmp/out.json","https://malicious.test/a.json",
                     "bad name.json","node1-comet.txt",123,None):
            bundle=copy.deepcopy(self.bundle)
            bundle["nodes"][0]["comet_status"]=name
            with self.assertRaises(ValueError):
                verify(bundle,self.base)
        bundle=copy.deepcopy(self.bundle)
        bundle["nodes"][1]["eth_chain_id"]=bundle["nodes"][0]["eth_chain_id"]
        with self.assertRaisesRegex(ValueError,"distinct local JSON"):
            verify(bundle,self.base)

    def test_symlinks_are_refused(self):
        path=self.base/"node1-comet.json"
        path.unlink()
        path.symlink_to(self.base/"node2-comet.json")
        with self.assertRaisesRegex(ValueError,"symlinked"):
            verify(self.bundle,self.base)

    def test_secret_and_duplicate_json_fields_refused(self):
        file=self.base/"node1-eth.json"
        file.write_text('{"result":"0x67932","result":"0x1"}')
        with self.assertRaisesRegex(ValueError,"duplicate JSON"):
            verify(self.bundle,self.base)
        file.write_text(json.dumps({"result":"0x67932","apiKey":"FAKE"}))
        with self.assertRaisesRegex(ValueError,"credential-like"):
            verify(self.bundle,self.base)

    def test_large_capture_rejected(self):
        (self.base/"node1-eth.json").write_text(" "*(1024*1024+1))
        with self.assertRaisesRegex(ValueError,"1 MiB"):
            verify(self.bundle,self.base)

    def test_command_line_is_read_only_and_no_go(self):
        manifest=self.base/"bundle.json"
        manifest.write_text(json.dumps(self.bundle),encoding="utf-8")
        proc=subprocess.run([sys.executable,
            str(Path(__file__).with_name("verify_four_validator_observations.py")),
            "--bundle",str(manifest)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr+proc.stdout)
        self.assertIn("NO_GO_REQUIRES_EXTERNAL_EVIDENCE",proc.stdout)
        self.assertIn("NO EXTERNAL ATTESTATION",proc.stdout)

if __name__=="__main__":
    unittest.main()
