# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Privi Vault: protection against "harvest now, decrypt later".

Data encrypted today with RSA or elliptic-curve key exchange can be recorded now and
decrypted once a large quantum computer exists. Privi Vault re-wraps long-lived data
(contracts, IP, records) under hybrid post-quantum encryption:

  key  = HKDF-SHA256( X25519 shared secret || ML-KEM shared secret,
                      info = suite || recipient key id || ephemeral X25519 || ML-KEM ciphertext )
  data = AES-256-GCM(key, nonce, plaintext, aad = envelope header)

Hybrid means an attacker must break BOTH X25519 (classical) and ML-KEM (FIPS 203, post-quantum).
Suites: X25519+ML-KEM-768 (default) and X25519+ML-KEM-1024 (CNSA 2.0 level KEM).

The server never keeps plaintext or private keys. For the strongest setup, run this module
locally (python -m privi_quantum.vault keygen|seal|open) so the data never leaves your machine,
and send Privi only the envelope's hash to get a signed, chain-anchored protection receipt.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import mlkem
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

FORMAT = "privi-vault-v1"
SUITES = {
    "X25519+ML-KEM-768": (mlkem.MLKEM768PrivateKey, mlkem.MLKEM768PublicKey),
    "X25519+ML-KEM-1024": (mlkem.MLKEM1024PrivateKey, mlkem.MLKEM1024PublicKey),
}
DEFAULT_SUITE = "X25519+ML-KEM-768"
MAX_PLAINTEXT = 5_000_000


class VaultError(ValueError):
    pass


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def b64d(s: str, what: str) -> bytes:
    try:
        return base64.b64decode(str(s), validate=True)
    except (ValueError, TypeError) as e:
        raise VaultError(f"{what} is not valid base64") from e


def _kid(x_pub: bytes, k_pub: bytes) -> str:
    return "pvk_" + hashlib.sha256(x_pub + k_pub).hexdigest()[:20]


def keygen(suite: str = DEFAULT_SUITE) -> dict:
    if suite not in SUITES:
        raise VaultError(f"suite must be one of {', '.join(SUITES)}")
    kpriv_cls, _ = SUITES[suite]
    x = X25519PrivateKey.generate()
    seed = os.urandom(64)
    k = kpriv_cls.from_seed_bytes(seed)
    x_pub, k_pub = x.public_key().public_bytes_raw(), k.public_key().public_bytes_raw()
    kid = _kid(x_pub, k_pub)
    return {"public_key": {"format": FORMAT, "suite": suite, "key_id": kid, "x25519": b64e(x_pub), "mlkem": b64e(k_pub)},
            "private_key": {"format": FORMAT, "suite": suite, "key_id": kid, "x25519": b64e(x.private_bytes_raw()),
                            "mlkem_seed": b64e(seed)}}


def _load_public(pk: dict) -> tuple[str, X25519PublicKey, object, str]:
    if not isinstance(pk, dict) or pk.get("suite") not in SUITES:
        raise VaultError("public_key must be a Privi Vault public key (from vault_keygen)")
    x_raw, k_raw = b64d(pk.get("x25519", ""), "x25519"), b64d(pk.get("mlkem", ""), "mlkem")
    try:
        x = X25519PublicKey.from_public_bytes(x_raw)
        k = SUITES[pk["suite"]][1].from_public_bytes(k_raw)
    except ValueError as e:
        raise VaultError(f"public key is malformed: {e}") from e
    kid = _kid(x_raw, k_raw)
    if pk.get("key_id") and pk["key_id"] != kid:
        raise VaultError("public key id does not match its key material")
    return pk["suite"], x, k, kid


def _derive(suite: str, kid: str, eph: bytes, ct: bytes, ss_x: bytes, ss_k: bytes) -> bytes:
    info = b"|".join([FORMAT.encode(), suite.encode(), kid.encode(), eph, ct])
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(ss_x + ss_k)


def _header(env: dict) -> bytes:
    h = {k: env[k] for k in ("format", "suite", "recipient_key_id", "label", "ephemeral_x25519", "mlkem_ciphertext", "nonce")}
    return json.dumps(h, sort_keys=True, separators=(",", ":")).encode()


def seal(plaintext: bytes, public_key: dict, label: str = "") -> dict:
    if len(plaintext) > MAX_PLAINTEXT:
        raise VaultError(f"data is larger than {MAX_PLAINTEXT // 1_000_000} MB; seal it locally with python -m privi_quantum.vault")
    suite, x_pub, k_pub, kid = _load_public(public_key)
    eph = X25519PrivateKey.generate()
    ss_x = eph.exchange(x_pub)
    ss_k, ct = k_pub.encapsulate()
    eph_pub = eph.public_key().public_bytes_raw()
    key = _derive(suite, kid, eph_pub, ct, ss_x, ss_k)
    nonce = os.urandom(12)
    env = {"format": FORMAT, "suite": suite, "recipient_key_id": kid, "label": str(label)[:200],
           "ephemeral_x25519": b64e(eph_pub), "mlkem_ciphertext": b64e(ct), "nonce": b64e(nonce)}
    env["ciphertext"] = b64e(AESGCM(key).encrypt(nonce, plaintext, _header(env)))
    env["plaintext_bytes"] = len(plaintext)
    return env


def envelope_sha256(env: dict) -> str:
    return hashlib.sha256(json.dumps(env, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def check_envelope(env: dict) -> dict:
    """Structure check without the private key (for receipts on locally sealed envelopes)."""
    if not isinstance(env, dict) or env.get("format") != FORMAT or env.get("suite") not in SUITES:
        raise VaultError("not a Privi Vault envelope")
    for k in ("recipient_key_id", "ephemeral_x25519", "mlkem_ciphertext", "nonce", "ciphertext"):
        if not env.get(k):
            raise VaultError(f"envelope is missing {k}")
    ct = b64d(env["mlkem_ciphertext"], "mlkem_ciphertext")
    want = 1088 if env["suite"].endswith("768") else 1568
    if len(ct) != want or len(b64d(env["ephemeral_x25519"], "ephemeral_x25519")) != 32 or len(b64d(env["nonce"], "nonce")) != 12:
        raise VaultError("envelope fields have the wrong sizes for its suite")
    return {"suite": env["suite"], "recipient_key_id": env["recipient_key_id"],
            "ciphertext_bytes": len(b64d(env["ciphertext"], "ciphertext")), "envelope_sha256": envelope_sha256(env)}


def open_(env: dict, private_key: dict) -> bytes:
    check_envelope(env)
    if not isinstance(private_key, dict) or private_key.get("suite") != env["suite"]:
        raise VaultError("private key suite does not match the envelope")
    try:
        x = X25519PrivateKey.from_private_bytes(b64d(private_key.get("x25519", ""), "x25519"))
        k = SUITES[env["suite"]][0].from_seed_bytes(b64d(private_key.get("mlkem_seed", ""), "mlkem_seed"))
    except ValueError as e:
        raise VaultError(f"private key is malformed: {e}") from e
    kid = _kid(x.public_key().public_bytes_raw(), k.public_key().public_bytes_raw())
    if kid != env["recipient_key_id"]:
        raise VaultError("this private key is not the envelope's recipient")
    eph = b64d(env["ephemeral_x25519"], "ephemeral_x25519")
    ct = b64d(env["mlkem_ciphertext"], "mlkem_ciphertext")
    key = _derive(env["suite"], kid, eph, ct, x.exchange(X25519PublicKey.from_public_bytes(eph)), k.decapsulate(ct))
    try:
        pt = AESGCM(key).decrypt(b64d(env["nonce"], "nonce"), b64d(env["ciphertext"], "ciphertext"), _header(env))
    except InvalidTag as e:
        raise VaultError("decryption failed: the envelope was modified or the key is wrong") from e
    return pt


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m privi_quantum.vault",
                                description="Privi Vault: hybrid post-quantum encryption, run locally")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("keygen"); g.add_argument("--suite", default=DEFAULT_SUITE); g.add_argument("--out", required=True,
                                                                                                    help="private key file to write")
    s = sub.add_parser("seal"); s.add_argument("file"); s.add_argument("--public-key", required=True); s.add_argument("--label", default="")
    o = sub.add_parser("open"); o.add_argument("envelope"); o.add_argument("--private-key", required=True); o.add_argument("--out", required=True)
    a = p.parse_args(argv)
    try:
        if a.cmd == "keygen":
            kp = keygen(a.suite)
            fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(kp["private_key"], f)
            print(json.dumps(kp["public_key"], indent=2))
        elif a.cmd == "seal":
            with open(a.public_key) as f:
                pk = json.load(f)
            with open(a.file, "rb") as f:
                env = seal(f.read(), pk, a.label or os.path.basename(a.file))
            print(json.dumps(env))
            print(f"envelope_sha256 {envelope_sha256(env)}", file=sys.stderr)
        else:
            with open(a.envelope) as f:
                env = json.load(f)
            with open(a.private_key) as f:
                sk = json.load(f)
            with open(a.out, "wb") as f:
                f.write(open_(env, sk))
    except (VaultError, OSError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
