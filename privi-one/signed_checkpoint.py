"""Offline, externally signed Privi ONE sandbox audit checkpoints.

A separate auditor signs a checkpoint obtained from the sandbox, using a private
key kept outside Render. Verification trusts ONLY pre-pinned public keys.

This is a development component, not live Ledger anchoring or proof of execution.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DOMAIN = b"PRIVI-ONE-OFFLINE-AUDIT-CHECKPOINT-V1\x00"
SCHEMA = "privi-one-signed-audit-checkpoint-v1"
KID = re.compile(r"^one-audit-[0-9a-f]{24}$")
HEX = re.compile(r"^[0-9a-f]{64}$")


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def key_id(public_key):
    if not isinstance(public_key, bytes) or len(public_key) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes")
    return "one-audit-" + hashlib.sha256(public_key).hexdigest()[:24]


def generate_keypair():
    """Offline-only helper. Never put a private key in Git or an HTTP response."""
    private = Ed25519PrivateKey.generate()
    secret = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                   serialization.NoEncryption())
    public = private.public_key().public_bytes(serialization.Encoding.Raw,
                                               serialization.PublicFormat.Raw)
    return secret, public


def check_checkpoint(checkpoint):
    if not isinstance(checkpoint, dict) or set(checkpoint) != {"schema", "sequence", "head", "mode"}:
        return False
    return (checkpoint["schema"] == "privi-one-external-checkpoint-v1"
            and checkpoint["mode"] == "LOCAL_SANDBOX_UNSIGNED_CHECKPOINT"
            and type(checkpoint["sequence"]) is int and checkpoint["sequence"] >= 0
            and isinstance(checkpoint["head"], str) and HEX.fullmatch(checkpoint["head"]) is not None)


def sign(checkpoint, *, private_key):
    if not check_checkpoint(checkpoint):
        raise ValueError("Invalid sandbox audit checkpoint")
    signing_key = Ed25519PrivateKey.from_private_bytes(private_key)
    public = signing_key.public_key().public_bytes(serialization.Encoding.Raw,
                                                   serialization.PublicFormat.Raw)
    body = {"schema": SCHEMA, "algorithm": "Ed25519", "key_id": key_id(public),
            "checkpoint": checkpoint}
    signature = signing_key.sign(DOMAIN + canonical(body))
    return {"body": body, "signature_b64url": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")}


def verify(envelope, *, pinned_public_keys):
    if not isinstance(envelope, dict) or set(envelope) != {"body", "signature_b64url"}:
        return False
    body = envelope.get("body")
    if (not isinstance(body, dict)
            or set(body) != {"schema", "algorithm", "key_id", "checkpoint"}
            or body.get("schema") != SCHEMA or body.get("algorithm") != "Ed25519"
            or not check_checkpoint(body.get("checkpoint"))):
        return False
    kid = body.get("key_id")
    if not isinstance(kid, str) or KID.fullmatch(kid) is None:
        return False
    if not isinstance(pinned_public_keys, dict):
        return False
    public = pinned_public_keys.get(kid)
    if not isinstance(public, bytes) or len(public) != 32 or key_id(public) != kid:
        return False
    sig_text = envelope.get("signature_b64url")
    if not isinstance(sig_text, str) or len(sig_text) > 100 or not re.fullmatch(r"[A-Za-z0-9_-]+", sig_text):
        return False
    try:
        signature = base64.urlsafe_b64decode(sig_text + "=" * (-len(sig_text) % 4))
        if len(signature) != 64:
            return False
        Ed25519PublicKey.from_public_bytes(public).verify(signature, DOMAIN + canonical(body))
        return True
    except (ValueError, TypeError, InvalidSignature, OverflowError):
        return False
