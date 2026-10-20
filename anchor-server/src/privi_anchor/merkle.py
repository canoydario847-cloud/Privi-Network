"""Sorted-pair SHA-256 Merkle trees.

node = sha256(min(a, b) || max(a, b)); a single leaf is its own root.
Sorting each pair means a proof is just the list of sibling hashes, with no
left/right flags, so anyone can re-check it with a few lines of code.
"""

from __future__ import annotations

import hashlib

ANCHOR_MAGIC = bytes.fromhex("50525641")  # "PRVA"
ANCHOR_VERSION = b"\x01"


def norm_hash(h: str) -> str:
    v = (h or "").strip().lower().removeprefix("0x")
    if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
        raise ValueError(f"not a 64-character hex SHA-256: {h!r}")
    return v


def _pair(a: bytes, b: bytes) -> bytes:
    return hashlib.sha256(min(a, b) + max(a, b)).digest()


def build(leaves_hex: list[str]) -> tuple[str, dict[str, list[str]]]:
    """Return (root_hex, {leaf_hex: proof}) for a set of leaves (duplicates removed)."""
    leaves = sorted(set(norm_hash(h) for h in leaves_hex))
    if not leaves:
        raise ValueError("at least one hash is required")
    level = [bytes.fromhex(h) for h in leaves]
    proofs: dict[str, list[str]] = {h: [] for h in leaves}
    owners = [[h] for h in leaves]  # which leaves sit under each node
    while len(level) > 1:
        nxt, nxt_owners = [], []
        for i in range(0, len(level), 2):
            if i + 1 == len(level):           # odd node is promoted unchanged
                nxt.append(level[i]); nxt_owners.append(owners[i]); continue
            a, b = level[i], level[i + 1]
            for h in owners[i]:
                proofs[h].append(b.hex())
            for h in owners[i + 1]:
                proofs[h].append(a.hex())
            nxt.append(_pair(a, b)); nxt_owners.append(owners[i] + owners[i + 1])
        level, owners = nxt, nxt_owners
    return level[0].hex(), proofs


def root_from_proof(leaf_hex: str, proof: list[str]) -> str:
    node = bytes.fromhex(norm_hash(leaf_hex))
    for sib in proof:
        node = _pair(node, bytes.fromhex(norm_hash(sib)))
    return node.hex()


def calldata(root_hex: str) -> str:
    """Transaction data carrying an anchor: 'PRVA' magic, version byte, 32-byte root."""
    return "0x" + (ANCHOR_MAGIC + ANCHOR_VERSION + bytes.fromhex(norm_hash(root_hex))).hex()


def root_from_calldata(data_hex: str) -> str | None:
    d = (data_hex or "").lower().removeprefix("0x")
    head = (ANCHOR_MAGIC + ANCHOR_VERSION).hex()
    if len(d) != len(head) + 64 or not d.startswith(head):
        return None
    return d[len(head):]
