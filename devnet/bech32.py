"""Convert a 0x EVM address to a bech32 Cosmos account address (BIP-173). Stdlib only."""
import sys

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _convertbits(data, frombits, tobits):
    acc, bits, ret, maxv = 0, 0, [], (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def encode(hrp: str, data: bytes) -> str:
    five = _convertbits(data, 8, 5)
    values = _hrp_expand(hrp) + five
    poly = _polymod(values + [0] * 6) ^ 1
    checksum = [(poly >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(CHARSET[d] for d in five + checksum)


def evm_to_cosmos(addr: str, hrp: str = "cosmos") -> str:
    h = addr.lower().removeprefix("0x")
    if len(h) != 40:
        raise ValueError(f"not a 20-byte address: {addr}")
    return encode(hrp, bytes.fromhex(h))


if __name__ == "__main__":
    print(evm_to_cosmos(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "cosmos"))
