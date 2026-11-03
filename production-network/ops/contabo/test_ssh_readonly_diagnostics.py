"""No-network tests for VNC-side, read-only SSH diagnostics."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parent
SCRIPT = BASE / "ssh_readonly_diagnostics.sh"

class ReadOnlySSHTests(unittest.TestCase):
    def test_bash_syntax(self):
        self.assertEqual(0, subprocess.run(["bash", "-n", str(SCRIPT)]).returncode)

    def test_no_mutating_system_commands(self):
        body = SCRIPT.read_text(encoding="utf-8")
        forbidden = ("systemctl start ", "systemctl restart ", "ufw allow ",
                     "ufw disable", "ufw enable", "iptables -", "nft add ",
                     "ssh-keygen ", "curl ", "wget ", "docker ", "evmd start")
        for word in forbidden:
            self.assertNotIn(word, body, word)

    def run_fixture(self, socket_output):
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp)
            programs = {
                "ss": "#!/bin/sh\nprintf '%s\\n' " + repr(socket_output) + "\n",
                "systemctl": "#!/bin/sh\nexit 0\n",
                "ufw": "#!/bin/sh\nprintf 'Status: active\\n'\n",
            }
            for name, value in programs.items():
                exe = tools / name
                exe.write_text(value)
                exe.chmod(0o700)
            env = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}")
            return subprocess.run(["bash", str(SCRIPT)], capture_output=True,
                                  text=True, env=env)

    def test_nonloopback_bind_not_claimed_external(self):
        r = self.run_fixture("LISTEN 0 128 0.0.0.0:22 0.0.0.0:*")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("External reachability is NOT proven", r.stdout)

    def test_loopback_only_is_blocker(self):
        r = self.run_fixture("LISTEN 0 128 127.0.0.1:22 0.0.0.0:*")
        self.assertEqual(r.returncode, 2)
        self.assertIn("loopback", r.stdout)

    def test_no_listener_is_blocker(self):
        r = self.run_fixture("")
        self.assertEqual(r.returncode, 2)
        self.assertIn("No TCP listener", r.stdout)

if __name__ == "__main__":
    unittest.main()
