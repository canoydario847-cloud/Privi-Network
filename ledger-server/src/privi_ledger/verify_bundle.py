#!/usr/bin/env python3
"""Verify a Privi Ledger evidence bundle completely offline.

    python verify_bundle.py bundle.json [--ed25519-key HEX] [--pq-key HEX]

Checks, with no network access:
  1. every entry's SHA-256 fingerprint and the hash chain linking them;
  2. the head entry's RFC 9162 inclusion proof against the signed tree head's root;
  3. the tree head's Ed25519 and ML-DSA-87 (FIPS 204) signatures;
  4. the bundle's own Ed25519 and ML-DSA-87 signatures.

Pin the issuer keys you obtained independently with --ed25519-key / --pq-key; otherwise
the keys embedded in the bundle are used (which proves integrity, not origin).
Needs Python 3.10+ and `pip install cryptography>=45` (ML-DSA needs a recent version).
"""

import argparse
import hashlib
import json
import sys

HASHED_FIELDS = ("org_id", "stream_id", "seq", "recorded_at", "actor", "action_type",
                 "summary", "resource", "outcome", "details", "prev_hash")
GENESIS = "0" * 64


def canonical(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(b):
    return hashlib.sha256(b).digest()


def fingerprint(e):
    f = {k: e[k] for k in HASHED_FIELDS}
    if not isinstance(f["details"], str):
        f["details"] = canonical(f["details"])
    return hashlib.sha256(canonical(f).encode()).hexdigest()


def verify_inclusion(leaf, index, size, path, root):
    if index >= size:
        return False
    fn, sn, r = index, size - 1, leaf
    for p in path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            r = sha(b"\x01" + p + r)
            if not fn & 1:
                while True:
                    fn >>= 1
                    sn >>= 1
                    if fn & 1 or fn == 0:
                        break
        else:
            r = sha(b"\x01" + r + p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and r == root


def ed25519_ok(pub_hex, msg_hex, sig_hex):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(bytes.fromhex(sig_hex), bytes.fromhex(msg_hex))
        return True
    except Exception:
        return False


def mldsa_ok(pub_hex, msg_hex, sig_hex):
    try:
        from cryptography.hazmat.primitives.asymmetric.mldsa import MLDSA87PublicKey
    except ImportError:
        return None  # library too old to check ML-DSA
    try:
        MLDSA87PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(bytes.fromhex(sig_hex), bytes.fromhex(msg_hex))
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle")
    ap.add_argument("--ed25519-key", help="pinned Privi Ed25519 public key (hex)")
    ap.add_argument("--pq-key", help="pinned Privi ML-DSA-87 public key (hex)")
    a = ap.parse_args()
    doc = json.load(open(a.bundle, encoding="utf-8"))
    b = doc["bundle"]
    keys = b["issuer_keys"]
    ed_key = a.ed25519_key or keys["classical"]["public_key_hex"]
    pq_key = a.pq_key or keys["post_quantum"]["public_key_hex"]
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        mark = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
        print(f"[{mark}] {name}" + (f" - {detail}" if detail else ""))

    # 1. entries and chain
    prev, ok, why = GENESIS, True, ""
    for i, e in enumerate(b["entries"], start=1):
        if e["seq"] != i:
            ok, why = False, f"sequence gap at {e['seq']}"
            break
        if e["prev_hash"] != prev:
            ok, why = False, f"broken link at seq {e['seq']}"
            break
        if fingerprint(e) != e["entry_hash"]:
            ok, why = False, f"entry {e['seq']} was altered"
            break
        prev = e["entry_hash"]
    check("hash chain of all entries", ok, why or f"{len(b['entries'])} entries")
    check("head matches bundle", prev == b["chain"]["head_hash"])

    # 2. inclusion proof
    ip, sth = b["inclusion_proof"], b["signed_tree_head"]
    leaf = sha(b"\x00" + bytes.fromhex(ip["entry_hash"]))
    check("head entry is in the Privi transparency log",
          ip["entry_hash"] == prev and verify_inclusion(leaf, ip["leaf_index"], ip["tree_size"],
                                                        [bytes.fromhex(p) for p in ip["audit_path"]],
                                                        bytes.fromhex(sth["tree_head"]["root_hash"])),
          f"leaf {ip['leaf_index']} of {ip['tree_size']}")

    # 3. tree head signatures
    th = hashlib.sha256(canonical(sth["tree_head"]).encode()).hexdigest()
    check("tree head body hash", th == sth["body_hash"])
    check("tree head Ed25519 signature", ed25519_ok(ed_key, th, sth["signatures"]["ed25519"]))
    check("tree head ML-DSA-87 signature", mldsa_ok(pq_key, th, sth["signatures"]["ml_dsa_87"]))

    # 4. bundle signatures
    bh = hashlib.sha256(canonical(b).encode()).hexdigest()
    check("bundle hash", bh == doc["bundle_hash"])
    check("bundle Ed25519 signature", ed25519_ok(ed_key, bh, doc["signatures"]["ed25519"]))
    check("bundle ML-DSA-87 signature", mldsa_ok(pq_key, bh, doc["signatures"]["ml_dsa_87"]))

    if b.get("onchain_checkpoint"):
        cp = b["onchain_checkpoint"]
        print(f"[INFO] on-chain checkpoint: seq {cp.get('seq')} tx {cp.get('tx_hash')} block {cp.get('block_number')} "
              f"(check online with Privi Anchor anchor_verify)")
    failed = any(r is False for r in results)
    print("\nRESULT:", "VALID" if not failed else "INVALID")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
