"""Railway staging cannot be rebranded as an audited PRVI financial mainnet."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from railway_staging_preflight import ManifestError, assess, reject_duplicate_keys

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "railway_staging_preflight.py"
SNAPSHOT = HERE / "railway_staging_observation.json"


class RailwayProviderSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    def test_observed_services_are_only_valueless_staging(self):
        errors, blockers = assess(self.data)
        self.assertEqual(errors, [])
        self.assertTrue(any("TEST chain" in x for x in blockers))
        self.assertTrue(any("one observed" in x for x in blockers))

    def test_financial_mainnet_never_authorized(self):
        result = subprocess.run([sys.executable, str(SCRIPT), str(SNAPSHOT),
                                 "--mode", "production"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 3)
        self.assertIn("NO-GO", result.stdout)

    def test_readonly_observation_can_be_audited(self):
        result = subprocess.run([sys.executable, str(SCRIPT), str(SNAPSHOT),
                                 "--mode", "staging"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("TEST only", result.stdout)

    def test_duplicate_services_fail(self):
        self.data["services"][1]["name"] = self.data["services"][0]["name"]
        errors, _ = assess(self.data)
        self.assertTrue(any("duplicate" in x for x in errors))

    def test_duplicate_volumes_fail(self):
        self.data["services"][1]["volume_id"] = self.data["services"][0]["volume_id"]
        errors, _ = assess(self.data)
        self.assertTrue(any("volume" in x for x in errors))

    def test_missing_online_status_fails(self):
        self.data["services"][4]["state"] = "crashed"
        errors, _ = assess(self.data)
        self.assertTrue(any("not observed healthy" in x for x in errors))

    def test_region_confusion_detected(self):
        self.data["services"][4]["region"] = "europe-west4"
        errors, _ = assess(self.data)
        self.assertTrue(any("region layout drift" in x for x in errors))

    def test_financial_relabel_rejected(self):
        for key,value in (
            ("network_class", "PRVI_MAINNET"),
            ("branch", "launch/mainnet-readiness-gate-20261017"),
            ("production_approval", "APPROVED"),
            ("genesis_sha256", "a" * 64),
        ):
            candidate = copy.deepcopy(self.data)
            candidate[key] = value
            errors, _ = assess(candidate)
            self.assertTrue(errors, f"{key} bypassed read-only staging classification")

    def test_secret_material_rejected_without_echo(self):
        self.data["password"] = "do-not-print-value"
        with self.assertRaisesRegex(ManifestError, "sensitive field"):
            assess(self.data)
        self.data.pop("password")
        self.data["source"] = "sk-proj-" + "x"*32
        with self.assertRaisesRegex(ManifestError, "credential material"):
            assess(self.data)

    def test_duplicate_json_key_rejected(self):
        with self.assertRaisesRegex(ManifestError, "duplicate JSON key"):
            json.loads('{"state":"online","state":"crashed"}',
                       object_pairs_hook=reject_duplicate_keys)


if __name__ == "__main__":
    unittest.main()
