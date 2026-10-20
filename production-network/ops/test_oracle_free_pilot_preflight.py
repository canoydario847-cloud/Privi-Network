"""Always Free budget test: protects CI against a silently billable pilot."""
import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("oci_free",HERE/"oracle_free_pilot_preflight.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
CANDIDATE=HERE/"oracle-always-free-pilot.candidate.json"

class PilotPolicyTests(unittest.TestCase):
    def setUp(self):
        self.doc=json.loads(CANDIDATE.read_text())
    def test_proposed_single_a1_pilot_fits_all_2026_quotas(self):
        self.assertEqual([],mod.assess(self.doc))
        self.assertFalse(self.doc["instance_provisioning_enabled"])
        self.assertFalse(self.doc["billing_upgrade_authorized"])
    def test_cpu_ram_disk_oversubscription_refused(self):
        for key,bad in (("ocpus",3),("memory_gb",13),("boot_volume_gb",201)):
            with self.subTest(resource=key):
                d=copy.deepcopy(self.doc)
                d["nodes"][0][key]=bad
                self.assertTrue(mod.assess(d))
    def test_two_hosts_must_share_total_allowance(self):
        d=copy.deepcopy(self.doc)
        d["nodes"]=[
          dict(self.doc["nodes"][0],id="privi-free-dev-01",ocpus=1,memory_gb=6,boot_volume_gb=50),
          dict(self.doc["nodes"][0],id="privi-free-dev-02",ocpus=1,memory_gb=6,boot_volume_gb=50),
        ]
        self.assertEqual([],mod.assess(d))
        d["nodes"][1]["memory_gb"]=7
        self.assertTrue(mod.assess(d))
        d["nodes"][1]["memory_gb"]=6
        d["nodes"][1]["ocpus"]=2
        self.assertTrue(mod.assess(d))
    def test_four_full_oci_nodes_cannot_claim_always_free(self):
        d=copy.deepcopy(self.doc)
        d["nodes"]=[dict(self.doc["nodes"][0],id=f"privi-free-dev-{i:02d}",ocpus=1,memory_gb=3,boot_volume_gb=50) for i in range(1,5)]
        self.assertTrue(any("four host" in msg for msg in mod.assess(d)))
    def test_paid_or_production_settings_rejected(self):
        for key,bad in (
            ("financial_network_enabled",True),
            ("real_prvi_issuance_enabled",True),
            ("instance_provisioning_enabled",True),
            ("billing_upgrade_authorized",True),
            ("resource_tier","Free Trial credit"),
            ("region","us-ashburn-1"),
        ):
            with self.subTest(key=key):
                d=copy.deepcopy(self.doc)
                d[key]=bad
                self.assertTrue(mod.assess(d))
        d=copy.deepcopy(self.doc)
        d["nodes"][0]["fee_denom"]="aprvi"
        self.assertTrue(mod.assess(d))
        d=copy.deepcopy(self.doc)
        d["nodes"][0]["public_rpc_exposed"]=True
        self.assertTrue(mod.assess(d))
    def test_suspicious_extra_fields_rejected(self):
        d=copy.deepcopy(self.doc)
        d["nodes"][0]["wallet_private_key"]="NEVER-STORE-HERE"
        self.assertTrue(mod.assess(d))
        d=copy.deepcopy(self.doc)
        d["oracle_api_token"]="NEVER-STORE-HERE"
        self.assertTrue(mod.assess(d))
    def test_duplicate_json_key_fails_closed(self):
        with self.assertRaises(ValueError):
            json.loads('{"phase":"x","phase":"y"}',object_pairs_hook=mod.unique_keys)
    def test_cli_requires_read_only_mode(self):
        res=subprocess.run([sys.executable,str(HERE/"oracle_free_pilot_preflight.py"),str(CANDIDATE)],
                           capture_output=True,text=True,check=False)
        self.assertEqual(0,res.returncode,res.stderr+res.stdout)
        self.assertIn("NO CLOUD REQUESTS SENT",res.stdout)
        self.assertIn("NO SPENDING AUTHORIZED",res.stdout)

if __name__=="__main__":
    unittest.main()
