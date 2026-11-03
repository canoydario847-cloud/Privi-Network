#!/usr/bin/env python3
"""Strict Cosmos Bech32 (BIP-173) PRVI account address validation.

Offline, pure stdlib, no API calls, no wallet/key generation. Address
syntax/checksum alone does NOT prove ownership, custody or permission.
"""
CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_MAP = {ch: i for i, ch in enumerate(CHARSET)}
GENERATOR = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)


def _polymod(values):
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1ffffff) << 5) ^ value
        for i, gen in enumerate(GENERATOR):
            if (top >> i) & 1:
                checksum ^= gen
    return checksum


def _hrp_expand(hrp):
    return [ord(ch) >> 5 for ch in hrp] + [0] + [ord(ch) & 31 for ch in hrp]


def _convertbits(data, frombits, tobits, pad=False):
    result, acc, bits = [], 0, 0
    maxvalue = (1 << tobits) - 1
    mask = (1 << (frombits + tobits - 1)) - 1
    for b in data:
        if b < 0 or b >> frombits:
            raise ValueError("invalid address data bits")
        acc = ((acc << frombits) | b) & mask
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            result.append((acc >> bits) & maxvalue)
    if pad:
        if bits:
            result.append((acc << (tobits - bits)) & maxvalue)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxvalue):
        raise ValueError("nonzero or excess address padding")
    return bytes(result)


def decode_privi_address(text):
    """Return 20-byte decoded account address or raise ValueError.

    Reject Bech32m, mixed-case, invalid charset, bad checksum, padded
    payloads, truncated/oversized addresses and other non-canonical input.
    """
    if not isinstance(text, str) or len(text) > 90 or len(text) < 8:
        raise ValueError("Privi account must be canonical Bech32")
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in text):
        raise ValueError("non-printable address character")
    if text != text.lower() or "1" not in text:
        raise ValueError("Privi account must be lowercase Bech32")
    pos = text.rfind("1")
    if pos < 1 or len(text) - pos < 7 or text[:pos] != "privi":
        raise ValueError("Privi account requires privi HRP and 6-character checksum")
    encoded = text[pos + 1:]
    try:
        values = [_MAP[ch] for ch in encoded]
    except KeyError as exc:
        raise ValueError("invalid Bech32 character") from exc
    if _polymod(_hrp_expand("privi") + values) != 1:
        raise ValueError("invalid Privi Bech32 checksum")
    raw = _convertbits(values[:-6], 5, 8)
    if len(raw) != 20:
        raise ValueError("Privi account must decode to exactly 20 bytes")
    return raw


def valid_privi_address(text):
    try:
        decode_privi_address(text)
        return True
    except ValueError:
        return False
