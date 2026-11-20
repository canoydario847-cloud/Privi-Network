"""Fail-closed acceptance checks using read-only synthetic GET responses."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location(
    "privi_done_functional", Path(__file__).with_name("functional_acceptance.py"))
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
SHA="a"*40
ZERO="0"*64

def fixture():
    return {
        "/health":{"ok":True,"service":"privi-one-demo","mode":"PRELAUNCH_SIMULATION"},
        "/api/version":{"service":"privi-one-demo","mode":"PRELAUNCH_SIMULATION",
                        "version_source":"RENDER_GIT_COMMIT_ENV",
                        "self_reported_commit":SHA,"independently_attested":False},
        "/api/audit":{"valid":True,"entries_checked":0,"head":ZERO,
                      "scope":"LOCAL_SQLITE_TAMPER_EVIDENCE_NOT_EXTERNAL_PROOF"},
        "/api/checkpoint":{"schema":"privi-one-external-checkpoint-v1",
                           "sequence":0,"head":ZERO,
                           "mode":"LOCAL_SANDBOX_UNSIGNED_CHECKPOINT"}
    }

def read(data):
    return lambda path:data[path]

class FunctionalReadOnlyTests(unittest.TestCase):
    def test_matching_functional_observations_are_not_certification(self):
        report=mod.observe(SHA,get=read(fixture()))
        self.assertEqual(report["result"],
                         "SANDBOX_READONLY_BEHAVIOR_OBSERVED_UNCERTIFIED")
        self.assertTrue(all(report["observations"].values()))
        self.assertFalse(report["execution_attested"])
        self.assertFalse(report["journal_crypto_proof"])
        self.assertFalse(report["customer_accepted"])
        self.assertFalse(report["invoiceable"])
        self.assertEqual(len(report["sha256_checksum_not_signature"]),64)

    def test_version_mismatch_fails_closed(self):
        data=fixture()
        data["/api/version"]["self_reported_commit"]="b"*40
        report=mod.observe(SHA,get=read(data))
        self.assertEqual(report["result"],"FUNCTIONAL_EVIDENCE_INCOMPLETE")
        self.assertFalse(report["observations"]["version_self_report"])

    def test_checkpoint_mismatch_fails_closed(self):
        data=fixture()
        data["/api/checkpoint"]["head"]="f"*64
        report=mod.observe(SHA,get=read(data))
        self.assertFalse(report["observations"]["unsigned_checkpoint_correlates"])

    def test_invalid_journal_scope_fails_closed(self):
        data=fixture()
        data["/api/audit"]["scope"]="BLOCKCHAIN_VERIFIED"
        report=mod.observe(SHA,get=read(data))
        self.assertFalse(report["observations"]["local_journal_audit_reported"])

    def test_missing_response_does_not_claim_success(self):
        data=fixture()
        del data["/api/checkpoint"]
        report=mod.observe(SHA,get=lambda p:data.get(p))
        self.assertEqual(report["result"],"FUNCTIONAL_EVIDENCE_INCOMPLETE")

    def test_network_failure_is_incomplete(self):
        def down(_):
            raise TimeoutError("unavailable")
        report=mod.observe(SHA,get=down)
        self.assertFalse(any(report["observations"].values()))

    def test_no_arbitrary_endpoints(self):
        with self.assertRaises(mod.ReadOnlyProbeUnavailable):
            mod._get("http://169.254.169.254/latest/meta-data")

    def test_invalid_sha_stops_before_network(self):
        with self.assertRaises(ValueError):
            mod.observe("main",get=lambda _:self.fail("should not fetch"))

    def test_deterministic_and_no_raw_journal_data(self):
        a=mod.observe(SHA,get=read(fixture()))
        b=mod.observe(SHA,get=read(fixture()))
        self.assertEqual(a,b)
        self.assertNotIn("receipt_json",str(a))
        self.assertNotIn("token",str(a).lower())

if __name__=="__main__":
    unittest.main()
