"""Offline mock tests; never execute any real Docker command."""
import importlib.util
import sys
import unittest
from pathlib import Path
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here))
spec=importlib.util.spec_from_file_location("fault_recovery",here/"fault_recovery.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ADDRESSES=[("%040X"%(i+1)) for i in range(4)]

def fake_get(url,route):
    index=mod.URLS.index(url)
    if route=="/status":
        return {"node_info":{"id":"id-%d"%index,"network":"local-4221"},
                "sync_info":{"latest_block_height":"30","catching_up":False}}
    if route.startswith("/block?"):
        return {"block_id":{"hash":"A"*64}}
    if route.startswith("/commit?"):
        return {"signed_header":{"commit":{
            "block_id":{"hash":"A"*64},
            "signatures":[
                {"validator_address":a,"block_id_flag":2,"signature":"signed"}
                for a in ADDRESSES[:3]]}}}
    raise AssertionError(route)

def fake_validators(url,height):
    return {a:100 for a in ADDRESSES}

class FaultTests(unittest.TestCase):
    def setUp(self):
        self.g=mod.get
        self.v=mod.validator_set
        mod.get=fake_get
        mod.validator_set=fake_validators
    def tearDown(self):
        mod.get=self.g
        mod.validator_set=self.v
    def test_three_nodes_can_commit_without_fourth(self):
        result=mod.inspect_commit(mod.URLS[:3],10,missing=ADDRESSES[3])
        self.assertEqual(result["signed_voting_power"],300)
        self.assertEqual(result["total_voting_power"],400)
        self.assertEqual(result["signed_validators"],3)
    def test_recovery_requires_rejoining_validator_signature(self):
        with self.assertRaisesRegex(ValueError,"not yet included"):
            mod.inspect_commit(mod.URLS,10,required=ADDRESSES[3])
    def test_outage_rejects_stopped_validator_signing(self):
        with self.assertRaisesRegex(ValueError,"still signed"):
            mod.inspect_commit(mod.URLS[:3],10,missing=ADDRESSES[1])
    def test_enforces_progress_after_baseline(self):
        with self.assertRaisesRegex(ValueError,"failed to progress"):
            mod.inspect_commit(mod.URLS[:3],30)
    def test_refuses_live_environment(self):
        with self.assertRaisesRegex(ValueError,"CI-only"):
            mod.safe_gate(Path("/tmp/.upstream-evm"),{"CI":"false"})
    def test_refuses_non_demo_dir(self):
        with self.assertRaisesRegex(ValueError,"non-upstream"):
            mod.safe_gate(Path("/tmp/production"),{
                "CI":"true","PRIVI_EPHEMERAL_TRANSFER_TEST":"1"
            })

if __name__=="__main__":
    unittest.main()
