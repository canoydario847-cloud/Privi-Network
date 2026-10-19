import subprocess
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent
PROBE = BASE / 'host_probe.sh'

class HostProbeTests(unittest.TestCase):
    def test_bash_syntax(self):
        self.assertEqual(subprocess.run(['bash', '-n', str(PROBE)]).returncode, 0)

    def test_probe_never_manages_services_or_downloads_code(self):
        code = PROBE.read_text(encoding='utf-8')
        forbidden = ['curl ', 'wget ', 'apt install', 'apt-get ', 'docker run',
                     'docker compose', 'systemctl start', 'systemctl enable',
                     'ufw enable', 'ufw allow', 'ssh-keygen ', 'evmd start']
        for token in forbidden:
            self.assertNotIn(token, code, token)

    def test_probe_has_no_external_network_dependency(self):
        code = PROBE.read_text(encoding='utf-8')
        self.assertNotIn('https://', code)
        self.assertNotIn('ssh ', code)
        self.assertNotIn('scp ', code)

if __name__ == '__main__':
    unittest.main()
