import unittest
from collections import defaultdict
from snapshot_priv import ZERO, TOKEN, TRANSFER, apply_transfer, parse_transfer, holder_from_topic


def topic(addr):
    return '0x' + '0' * 24 + addr[2:]


class ERC20AuditTests(unittest.TestCase):
    def test_mint_transfer_burn(self):
        a = '0x' + 'a' * 40
        b = '0x' + 'b' * 40
        balances = defaultdict(int)
        apply_transfer(balances, ZERO, a, 100)
        apply_transfer(balances, a, b, 40)
        apply_transfer(balances, b, ZERO, 10)
        self.assertEqual(balances[a], 60)
        self.assertEqual(balances[b], 30)
        self.assertEqual(sum(balances.values()), 90)

    def test_negative_balance_fails_closed(self):
        with self.assertRaises(ValueError):
            apply_transfer(defaultdict(int), '0x' + '1' * 40, ZERO, 12)

    def test_decode_event(self):
        a = '0x' + 'a' * 40
        b = '0x' + 'b' * 40
        e = {'address': TOKEN, 'removed': False, 'topics': [TRANSFER, topic(a), topic(b)],
             'data': '0x' + format(15, '064x')}
        self.assertEqual(parse_transfer(e, TOKEN), (a, b, 15))
        self.assertEqual(holder_from_topic(topic(a)), a)

    def test_wrong_event_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_transfer({'address': TOKEN, 'topics': [], 'data': '0x'}, TOKEN)


if __name__ == '__main__':
    unittest.main()
