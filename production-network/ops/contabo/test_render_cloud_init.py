"""Offline security tests for no-credentials, no-side-effects render tool."""
import base64
import subprocess
import struct
import tempfile
import unittest
from pathlib import Path
from render_cloud_init import render, validate_public_key

HERE = Path(__file__).parent
TEMPLATE = (HERE / 'cloud-init.template.yaml').read_text()

def valid_pub() -> str:
    blob = struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32) + b'\x11' * 32
    return 'ssh-ed25519 ' + base64.b64encode(blob).decode() + ' staging@example'

class RenderTests(unittest.TestCase):
    def test_valid_public_key(self):
        output = validate_public_key(valid_pub())
        self.assertTrue(output.startswith('ssh-ed25519 '))
        self.assertNotIn('@', output)

    def test_render_four_independent_hostnames(self):
        results = [render(TEMPLATE, valid_pub(), i) for i in range(1, 5)]
        self.assertEqual(len(set(results)), 4)
        for i, content in enumerate(results, 1):
            self.assertIn(f'hostname: privi-stage-{i:02d}', content)
            self.assertNotIn('REPLACE_WITH', content)
            self.assertNotIn('runcmd:', content)

    def test_refuses_private_key(self):
        with self.assertRaises(ValueError):
            validate_public_key('-----BEGIN OPENSSH PRIVATE KEY-----\nabc')

    def test_refuses_two_keys(self):
        with self.assertRaises(ValueError):
            validate_public_key(valid_pub() + '\n' + valid_pub())

    def test_refuses_yaml_comment_injection(self):
        with self.assertRaises(ValueError):
            validate_public_key(valid_pub() + ' #hello: unsafe')

    def test_rejects_corrupt_blob(self):
        with self.assertRaises(ValueError):
            validate_public_key('ssh-ed25519 AAAA')

    def test_rejects_missing_reviewed_template_marker(self):
        with self.assertRaises(ValueError):
            render(TEMPLATE.replace('REPLACE_WITH_HOSTNAME', 'privi-stage'), valid_pub(), 1)

    def test_rejects_unsafe_template(self):
        with self.assertRaises(ValueError):
            render(TEMPLATE + '\nruncmd:\n - something\n', valid_pub(), 1)

    def test_rejects_host_outside_approved_range(self):
        with self.assertRaises(ValueError):
            render(TEMPLATE, valid_pub(), 5)

    def test_cli_renders_files_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'admin.pub'
            source.write_text(valid_pub())
            out = root / 'cloud-init'
            proc = subprocess.run(['python3', str(HERE / 'render_cloud_init.py'),
                                   '--ssh-public-key-file', str(source),
                                   '--count', '4', '--output-dir', str(out)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(len(list(out.glob('*.yaml'))), 4)
            self.assertTrue('NO CLOUD REQUESTS' in proc.stdout)
            again = subprocess.run(['python3', str(HERE / 'render_cloud_init.py'),
                                    '--ssh-public-key-file', str(source),
                                    '--output-dir', str(out)], capture_output=True)
            self.assertNotEqual(again.returncode, 0)

    def test_cli_rejects_non_pub_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'id_ed25519'
            source.write_text(valid_pub())
            proc = subprocess.run(['python3', str(HERE / 'render_cloud_init.py'),
                                   '--ssh-public-key-file', str(source),
                                   '--output-dir', str(root / 'out')], capture_output=True)
            self.assertNotEqual(proc.returncode, 0)

if __name__ == '__main__':
    unittest.main()
