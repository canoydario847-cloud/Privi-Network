import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("owner_validator_preflight",HERE/"owner_validator_preflight.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
CANDIDATE=HERE/"owner-operated-validators.candidate.json"

class OwnerTopologyTests(unittest.TestCase):
    def setUp(self):
        self.m=module.load(CANDIDATE)
    def check(self):
        return module.assess(self.m)
    def test_draft_declares_single_owner_and_exact_four(self):
        errors, blockers=self.check()
        self.assertEqual([], errors)
        self.assertGreater(len(blockers),0)
        self.assertEqual(4,len(self.m["validators"]))
        self.assertEqual(1,self.m["independent_operator_count"])
        self.assertFalse(self.m["financial_launch_enabled"])
    def test_duplicate_host_and_signing_key_are_rejected(self):
        for key,value in [
            ("host_id","host-a"),("fault_domain","power-site-a"),
            ("private_p2p_ip","10.123.1.10"),
            ("node_id","a"*40),
            ("consensus_pubkey_sha256","a"*64),
            ("sentry_reference","sentry-a"),
        ]:
            with self.subTest(key=key):
                d=copy.deepcopy(self.m)
                for item in d["validators"][:2]:
                    item[key]=value
                errors,_=module.assess(d)
                self.assertTrue(any(f"duplicated {key}" in x for x in errors),errors)
    def test_public_exposure_and_nonloopback_admin_ports_are_rejected(self):
        for addr in ["8.8.8.8","0.0.0.0","127.0.0.1","fe80::1"]:
            with self.subTest(ip=addr):
                d=copy.deepcopy(self.m)
                d["validators"][0]["private_p2p_ip"]=addr
                errors,_=module.assess(d)
                self.assertTrue(any("P2P IP" in e for e in errors),errors)
        for name in ["rpc_listen","metrics_listen"]:
            d=copy.deepcopy(self.m)
            d["validators"][0][name]="0.0.0.0"
            self.assertTrue(any("loopback-only" in e for e in module.assess(d)[0]))
    def test_unapproved_signer_type_and_dev_keyring_rejected(self):
        for val in ("keyring-test","shared-wallet","plaintext-file","hot-key"):
            d=copy.deepcopy(self.m)
            d["validators"][0]["signer_type"]=val
            errors,_=module.assess(d)
            self.assertTrue(any("unsafe signer type" in e for e in errors))
    def test_wrong_validator_count_operator_voting_power_fails(self):
        for mutation in (
            lambda d:d["validators"].pop(),
            lambda d:d.update({"independent_operator_count":4}),
            lambda d:d["validators"][0].update({"operator":"external"}),
            lambda d:d["validators"][0].update({"voting_power_percent":50}),
            lambda d:d.update({"financial_launch_enabled":True}),
            lambda d:d.update({"production_ready":True}),
        ):
            d=copy.deepcopy(self.m)
            mutation(d)
            self.assertTrue(module.assess(d)[0])
    def test_secrets_must_never_be_embedded_in_inventory(self):
        d=copy.deepcopy(self.m)
        d["validators"][0]["private_key"]="SENSITIVE-NOT-FOR-GIT"
        errors,_=module.assess(d)
        self.assertTrue(any("sensitive field" in e for e in errors))
        d=copy.deepcopy(self.m)
        d["validators"][0]["signer_attestation"]="-----BEGIN RSA PRIVATE KEY-----"
        errors,_=module.assess(d)
        self.assertTrue(any("credential included" in e for e in errors))
    def test_duplicate_json_keys_are_rejected(self):
        with self.assertRaisesRegex(module.InvalidInventory,"duplicate JSON key"):
            json.loads('{"operator":"Privi World Corp","operator":"other"}',object_pairs_hook=module.no_duplicate_keys)
    def test_preflight_never_self_certifies(self):
        cmd=[sys.executable,str(HERE/"owner_validator_preflight.py"),str(CANDIDATE),"--mode","preflight"]
        res=subprocess.run(cmd,capture_output=True,text=True,check=False)
        self.assertEqual(3,res.returncode,res.stdout+res.stderr)
        self.assertIn("NO-GO",res.stdout)
        self.assertIn("Financial PRVI mainnet: NOT ACTIVE",res.stdout)
    def test_draft_passes_structure_only(self):
        cmd=[sys.executable,str(HERE/"owner_validator_preflight.py"),str(CANDIDATE),"--mode","draft"]
        res=subprocess.run(cmd,capture_output=True,text=True,check=False)
        self.assertEqual(0,res.returncode,res.stdout+res.stderr)
        self.assertIn("DRAFT ACCEPTED",res.stdout)
    def test_incomplete_manifest_remains_blocked(self):
        errors,blocks=self.check()
        self.assertFalse(errors)
        self.assertIn("release evidence missing: genesis_sha256",blocks)
        self.assertTrue(any("signer type not selected" in x for x in blocks))

if __name__=="__main__":
    unittest.main()
