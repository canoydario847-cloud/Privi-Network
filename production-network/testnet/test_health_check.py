import unittest
from health_check import check


class HealthCheckTest(unittest.TestCase):
    def test_good(self):
        nodes = [{'node_id': str(n), 'network': 'privi-testnet-1', 'height': 100+n,
                  'catching_up': False} for n in range(4)]
        self.assertEqual(check(nodes, 'privi-testnet-1')['nodes'], 4)

    def test_duplicate_nodes_rejected(self):
        nodes = [{'node_id': 'one', 'network': 'privi-testnet-1', 'height': 100,
                  'catching_up': False} for _ in range(4)]
        with self.assertRaises(ValueError):
            check(nodes, 'privi-testnet-1')

    def test_lag_rejected(self):
        nodes = [{'node_id': str(n), 'network': 'privi-testnet-1', 'height': 100+n*20,
                  'catching_up': False} for n in range(4)]
        with self.assertRaises(ValueError):
            check(nodes, 'privi-testnet-1')


if __name__ == '__main__':
    unittest.main()
