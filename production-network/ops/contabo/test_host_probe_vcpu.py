"""Offline unit tests for Cloud VPS 8 CPU readiness threshold; no SSH/network."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PROBE = HERE / "host_probe.sh"


class ProbeVcpuTests(unittest.TestCase):
    def run_probe(self, advertised, actual=8):
        with tempfile.TemporaryDirectory() as td:
            tool = Path(td) / "nproc"
            tool.write_text(f"#!/bin/sh\nprintf '%s\\n' '{actual}'\n")
            tool.chmod(0o700)
            env = dict(os.environ)
            env["PATH"] = td + os.pathsep + env.get("PATH", "")
            if advertised is None:
                env.pop("PRIVI_EXPECTED_VCPU", None)
            else:
                env["PRIVI_EXPECTED_VCPU"] = str(advertised)
            return subprocess.run(["bash", str(PROBE)],capture_output=True,
                                  text=True,env=env,timeout=10)

    def test_shell_parses(self):
        result = subprocess.run(["bash","-n",str(PROBE)],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_new_8_core_server_is_required_when_selected(self):
        result=self.run_probe(8,6)
        self.assertEqual(result.returncode,2)
        self.assertIn("FAIL: Fewer than 8 available vCPU",result.stdout)

    def test_8_cores_satisfy_configured_8_core_floor(self):
        result=self.run_probe(8,8)
        self.assertIn("PASS: At least 8 available vCPU",result.stdout)
        self.assertNotIn("Fewer than 8 available vCPU",result.stdout)

    def test_previous_six_core_default_remains_unchanged(self):
        result=self.run_probe(None,6)
        self.assertIn("PASS: At least 6 available vCPU",result.stdout)

    def test_invalid_threshold_never_runs_other_probes(self):
        for bad in ("0","129","-1","8.0","eight","", "8; echo injected",
                    "999999999999999999999999999999999"):
            if bad == "":
                # An explicitly empty environment variable chooses the safe
                # backward-compatible default, not an unsafe shell eval.
                result=self.run_probe(bad,6)
                self.assertIn("At least 6 available vCPU",result.stdout)
            else:
                result=self.run_probe(bad)
                self.assertEqual(result.returncode,2,bad)
                self.assertIn("Expected vCPU threshold",result.stdout)
                self.assertNotIn("injected",result.stdout)

    def test_no_ssh_install_or_cloud_deployment(self):
        body=PROBE.read_text()
        for forbidden in ("ssh root@", "curl ", "wget ", "apt install",
                          "docker run", "evmd start", "ufw allow", "systemctl restart"):
            self.assertNotIn(forbidden,body)


if __name__ == "__main__":
    unittest.main()
