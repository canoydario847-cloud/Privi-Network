#!/usr/bin/env python3
"""Offline, synthetic address tests — NO keys, wallets or funds generated."""
import unittest
from bech32_accounts import (
    _convertbits, _hrp_expand, _polymod, CHARSET,
    decode_privi_address, valid_privi_address,
)


def test_address(seed):
    """A checksum-correct encoding of dummy payload bytes, for tests only."""
    if type(seed) is not int or seed < 0 or seed >= 255:
        raise ValueError("synthetic seed must fit in a byte")
    payload = bytes([seed + 1]) * 20
    values = list(_convertbits(payload, 8, 5, pad=True))
    packed = _polymod(_hrp_expand("privi") + values + [0]*6) ^ 1
    checksum = [(packed >> (5 * (5 - j))) & 31 for j in range(6)]
    return "privi1" + "".join(CHARSET[n] for n in values + checksum)


class Bech32ChecksumTests(unittest.TestCase):
    def test_synthetic_20_byte_addresses_decode_and_roundtrip(self):
        for seed in (0, 1, 15, 64, 128, 254):
            encoded = test_address(seed)
            self.assertTrue(valid_privi_address(encoded))
            self.assertEqual(decode_privi_address(encoded), bytes([seed + 1])*20)
            self.assertEqual(encoded, encoded.lower())

    def test_single_character_error_is_rejected_even_if_prefix_matches(self):
        original = test_address(10)
        bad = original[:-1] + ("q" if original[-1] != "q" else "p")
        self.assertTrue(original.startswith("privi1"))
        self.assertFalse(valid_privi_address(bad))

    def test_wrong_prefix_and_case_rejected(self):
        s = test_address(1)
        self.assertFalse(valid_privi_address(s.upper()))
        self.assertFalse(valid_privi_address(s[0].upper() + s[1:]))
        self.assertFalse(valid_privi_address("cosmos" + s[5:]))
        self.assertFalse(valid_privi_address("privi1"+"q"*38))

    def test_reject_truncation_bad_padding_wrong_byte_lengths(self):
        s = test_address(2)
        self.assertFalse(valid_privi_address(s[:-5]))
        self.assertFalse(valid_privi_address(s + "qq"))
        self.assertFalse(valid_privi_address(None))
        self.assertFalse(valid_privi_address("privi1" + "x"*90))

    def test_known_bech32_checksum_vectors_from_bip173(self):
        # Known standard Bech32 strings, structurally good but rejected
        # as native Privi account addresses (wrong HRP/payload length).
        self.assertFalse(valid_privi_address("A12UEL5L"))
        self.assertFalse(valid_privi_address("a12uel5l"))
        self.assertFalse(valid_privi_address("abcdef1l7aum6echk45nj3s0wdvt2fg8x9yrzpqzd3ryx"))
        self.assertFalse(valid_privi_address("privi1invalid"))


if __name__ == "__main__":
    unittest.main()
