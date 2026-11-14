import unittest
from genesis_supply_audit import parse_amount, CAP_BASE

class TestCanonicalAmounts(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(parse_amount("0", "test"), 0)
        self.assertEqual(parse_amount(str(CAP_BASE), "test"), CAP_BASE)

    def test_invalid_amounts(self):
        for value in ("00", "01", "0001", "-1", "+1", "1.0", "", "9" * 50000, chr(0x0661)):
            with self.subTest(value=value[:10]), self.assertRaises(ValueError):
                parse_amount(value, "test")

if __name__ == "__main__":
    unittest.main()
