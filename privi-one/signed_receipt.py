"""Privi ONE sandbox Ed25519 receipt signatures, independently verifiable offline.

Not a blockchain receipt. Not proof that a third-party action occurred.
Install cryptography>=43,<47. Never commit production private keys.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DOMAIN = b"PRIVI-ONE-SANDBOX-RECEIPT-V1\x00"
ALGORITHM = "Ed25519"
KID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{4,80}$")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, ensure_ascii=False).encode("utf-8")


def b64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def unb64(value):
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError("invalid base64")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_keypair():
    """Generate a disposable sandbox keypair. Caller controls secret storage."""
    key = Ed25519PrivateKey.generate()
    raw_secret = key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    pub = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return raw_secret, pub


def key_id(public_key):
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise ValueError("invalid public key")
    return "privi-one-" + hashlib.sha256(public_key).hexdigest()[:16]


def sign_receipt(receipt, *, private_key_bytes, key_id_value=None):
    """Sign a receipt object under a domain-separated Ed25519 signature.

    The signer signs what it was given. A signed DEMO receipt is still a DEMO.
    """
    if not isinstance(receipt, dict) or receipt.get("mode") != "PRELAUNCH_SIMULATION_NO_EXTERNAL_EXECUTION":
        raise ValueError("only Privi ONE prelaunch receipts may be signed")
    key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    kid = key_id(public)
    if key_id_value is not None and key_id_value != kid:
        raise ValueError("signing key identity mismatch")
    body = {"domain": "privi-one-sandbox-receipt-v1", "key_id": kid,
            "algorithm": ALGORITHM, "receipt": receipt}
    signature = key.sign(DOMAIN + canonical(body))
    return {"signed": body, "signature_b64url": b64(signature)}


def verify_receipt(envelope, *, trusted_keys):
    """Verify against an independently provided, pinned key mapping.

    NEVER read an untrusted key from the signed envelope itself.
    """
    if not isinstance(envelope, dict) or not isinstance(trusted_keys, dict):
        return False
    body = envelope.get("signed")
    if not isinstance(body, dict) or set(body) != {"domain", "key_id", "algorithm", "receipt"}:
        return False
    if body["domain"] != "privi-one-sandbox-receipt-v1" or body["algorithm"] != ALGORITHM:
        return False
    receipt = body.get("receipt")
    if not isinstance(receipt, dict) or receipt.get("mode") != "PRELAUNCH_SIMULATION_NO_EXTERNAL_EXECUTION":
        return False
    kid = body.get("key_id")
    if not isinstance(kid, str) or not KID_PATTERN.fullmatch(kid):
        return False
    public = trusted_keys.get(kid)
    if not isinstance(public, bytes) or len(public) != 32:
        return False
    if key_id(public) != kid:
        return False
    try:
        sig = unb64(envelope.get("signature_b64url"))
        if len(sig) != 64:
            return False
        Ed25519PublicKey.from_public_bytes(public).verify(sig, DOMAIN + canonical(body))
        return True
    except (InvalidSignature, ValueError, TypeError, OverflowError):
        return False
