import unittest
from health_check import check, status
from unittest.mock import patch
import urllib.request


class HealthCheckTest(unittest.TestCase):
    def test_rpc_url_rejects_credentials_and_unexpected_paths(self):
        invalid = (
            'http://user:password@localhost:26657',
            'http://localhost:26657/private',
            'http://localhost:26657/?token=secret',
            'http://localhost:26657/#fragment',
            'file:///etc/passwd',
            'localhost:26657',
        )
        with patch.object(urllib.request, 'urlopen') as urlopen:
            for url in invalid:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    status(url)
            urlopen.assert_not_called()

    def test_good(self):
        nodes = [{'node_id': str(n), 'network': 'privi-testnet-1', 'height': 100+n,
                  'catching_up': False} for n in range(4)]
        self.assertEqual(check(nodes, 'privi-testnet-1')['nodes'], 4)

    def test_duplicate_nodes_rejected(self):
        nodes = [{'node_id': 'one', 'network': 'privi-testnet-1', 'height': 100,
                  'catching_up': False} for _ in range(4)]
        with self.assertRaises(ValueError):
            check(nodes, 'privi-testnet-1')

    def test_missing_node_identity_rejected(self):
        for missing in ('', '   ', None):
            nodes = [{'node_id': str(n), 'network': 'privi-testnet-1', 'height': 100,
                      'catching_up': False} for n in range(4)]
            nodes[0]['node_id'] = missing
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'Missing'):
                check(nodes, 'privi-testnet-1')

    def test_invalid_block_heights_rejected(self):
        for height in (None, '100', 0, -1, True, 100.5):
            nodes = [{'node_id': str(n), 'network': 'privi-testnet-1',
                      'height': 100, 'catching_up': False} for n in range(4)]
            nodes[0]['height'] = height
            with self.subTest(height=height), self.assertRaisesRegex(ValueError, 'Invalid'):
                check(nodes, 'privi-testnet-1')

    def test_malformed_sync_flags_rejected(self):
        for flag in (None, 0, 1, 'false', 'true', ''):
            nodes = [{'node_id': str(n), 'network': 'privi-testnet-1',
                      'height': 100, 'catching_up': False} for n in range(4)]
            nodes[0]['catching_up'] = flag
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'Invalid'):
                check(nodes, 'privi-testnet-1')

    def test_lag_rejected(self):
        nodes = [{'node_id': str(n), 'network': 'privi-testnet-1', 'height': 100+n*20,
                  'catching_up': False} for n in range(4)]
        with self.assertRaises(ValueError):
            check(nodes, 'privi-testnet-1')


if __name__ == '__main__':
    unittest.main()
