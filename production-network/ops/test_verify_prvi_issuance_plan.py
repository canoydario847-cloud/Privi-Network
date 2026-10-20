"""No real native PRVI issuance: rigorous unsigned allocation arithmetic tests."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from strict_json_evidence import load
from verify_prvi_issuance_plan import BASE, CAP, validate

HERE=Path(__file__).resolve().parent
MANIFEST=HERE/"prvi_issuance_plan.UNSIGNED.json"
SCRIPT=HERE/"verify_prvi_issuance_plan.py"


class UnsignedPRVIAllocationChecks(unittest.TestCase):
    def setUp(self):
        self.plan=load(MANIFEST)

    def test_proposed_one_billion_allocation_math(self):
        proof=validate(self.plan)
        self.assertEqual(proof["base_aprvi"],str(CAP*BASE))
        self.assertEqual(proof["whole_prvi"],str(CAP))
        self.assertEqual(proof["coins_minted"],"0")
        self.assertEqual(proof["financial_mainnet"],"NOT_LIVE")

    def test_launch_mode_always_refuses_draft(self):
        proc=subprocess.run([sys.executable,str(SCRIPT),str(MANIFEST),
                             "--mode","launch"],capture_output=True,text=True)
        self.assertEqual(proc.returncode,3)
        self.assertIn("NO-GO",proc.stdout)

    def test_draft_mode_passes_arithmetic_only(self):
        proc=subprocess.run([sys.executable,str(SCRIPT),str(MANIFEST),
                             "--mode","draft"],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assertIn("UNSIGNED_DRAFT_ARITHMETIC_ONLY",proc.stdout)

    def test_inflated_bucket_rejected(self):
        self.plan["allocations"][0]["whole_prvi"]="400000001"
        with self.assertRaisesRegex(ValueError,"bucket allocation"):
            validate(self.plan)

    def test_incorrect_18_decimal_multiplication_rejected(self):
        self.plan["allocations"][0]["base_aprvi"]=str(400000000*10**6)
        with self.assertRaisesRegex(ValueError,"bucket allocation"):
            validate(self.plan)

    def test_reordered_buckets_allowed_but_missing_rejected(self):
        self.plan["allocations"].reverse()
        self.assertEqual(validate(self.plan)["bucket_count"],5)
        self.plan["allocations"].pop()
        with self.assertRaises(ValueError):
            validate(self.plan)

    def test_duplicate_bucket_rejected(self):
        self.plan["allocations"][0]["bucket"]="treasury"
        with self.assertRaisesRegex(ValueError,"duplicate"):
            validate(self.plan)

    def test_no_unapproved_recipient_or_signature(self):
        self.plan["allocations"][0]["recipient_public_address"]="cosmos1abc"
        with self.assertRaisesRegex(ValueError,"do not assign recipient"):
            validate(self.plan)
        self.plan=load(MANIFEST)
        self.plan["signed_genesis_sha256"]="f"*64
        with self.assertRaisesRegex(ValueError,"unsigned draft"):
            validate(self.plan)

    def test_no_silent_circulating_supply_confusion(self):
        for value in ("1000000001",1000000000,True,"1e9","0000001000000000"):
            altered=copy.deepcopy(self.plan)
            altered["proposed_genesis_whole_prvi"]=value
            with self.assertRaises(ValueError):
                validate(altered)

    def test_no_fake_launch_status(self):
        self.plan["state"]="LIVE"
        with self.assertRaisesRegex(ValueError,"state"):
            validate(self.plan)

    def test_no_credential_fields_in_manifest(self):
        self.plan["mnemonic"]="do not display"
        with self.assertRaises(ValueError):
            validate(self.plan)

    def test_duplicate_raw_json_properties_fail(self):
        from strict_json_evidence import _unique_pairs
        with self.assertRaisesRegex(ValueError,"duplicate JSON property"):
            json.loads('{"state":"UNSIGNED_DRAFT_NOT_MINTED","state":"LIVE"}',
                       object_pairs_hook=_unique_pairs)


if __name__=="__main__":
    unittest.main()
