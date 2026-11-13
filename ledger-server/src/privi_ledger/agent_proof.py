"""Privi Agent Proof: independently verify signed authorization and execution receipts.

Requires out-of-band pinned Ed25519 public keys. Caller-supplied keys are not
an identity authority; deployments MUST pin against a trusted registry.
No private keys, instructions, payloads or customer data are stored.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
AUTH_FIELDS = frozenset(("version", "tenant_id", "actor_id", "decision_id",
    "action_id", "policy_digest", "request_digest", "decision", "issued_at_ms",
    "expires_at_ms", "signer_id", "signature"))
ACK_FIELDS = frozenset(("version", "decision_id", "action_id",
    "authorization_digest", "status", "result_digest", "recorded_at_ms",
    "executor_id", "signer_id", "signature"))
MAX_WINDOW_MS = 300_000
MAX_INPUT_BYTES = 12_000


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf8")


def _without_signature(data: dict) -> dict:
    return {key: value for key, value in data.items() if key != "signature"}


def _digest(data: dict) -> str:
    return hashlib.sha256(_canonical(_without_signature(data))).hexdigest()


def _decode(value: str, n: int) -> bytes:
    if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("malformed base64url")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(raw) != n or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != value:
        raise ValueError("malformed key or signature")
    return raw


def _id(value: Any) -> bool:
    return isinstance(value, str) and bool(IDENT.fullmatch(value))


def _hash(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _verify(receipt: dict, key: str) -> None:
    pub = Ed25519PublicKey.from_public_bytes(_decode(key, 32))
    pub.verify(_decode(receipt["signature"], 64), _canonical(_without_signature(receipt)))


def verify_agent_proof(authorization: dict, acknowledgment: dict,
                       trusted_keys: dict, *, now_ms: int | None = None) -> dict:
    """Fail-closed verification. 'verified' means a two-signer synthetic proof,
    not an assertion that a remote physical action definitely occurred.
    """
    def deny(reason: str) -> dict:
        return {"verified": False, "authorized_and_completed": False,
                "reason": reason, "storage": "none"}

    try:
        if not isinstance(authorization, dict) or not isinstance(acknowledgment, dict) or not isinstance(trusted_keys, dict):
            return deny("malformed_input")
        if (len(_canonical(authorization)) + len(_canonical(acknowledgment)) +
                len(_canonical(trusted_keys)) > MAX_INPUT_BYTES):
            return deny("input_too_large")
        if set(authorization) != AUTH_FIELDS or set(acknowledgment) != ACK_FIELDS:
            return deny("invalid_schema")
        a, e = authorization, acknowledgment
        if a["version"] != "privi-agent-proof-v1" or e["version"] != "privi-agent-proof-v1":
            return deny("unsupported_version")
        if not all(_id(a[f]) for f in ("tenant_id","actor_id","decision_id","action_id","signer_id")):
            return deny("invalid_authorization_identity")
        if not all(_id(e[f]) for f in ("decision_id","action_id","executor_id","signer_id")):
            return deny("invalid_execution_identity")
        if not all(_hash(a[f]) for f in ("policy_digest", "request_digest")):
            return deny("invalid_authorization_hash")
        if not all(_hash(e[f]) for f in ("authorization_digest", "result_digest")):
            return deny("invalid_execution_hash")
        if a["decision"] not in ("ALLOW","DENY","ESCALATE") or e["status"] not in ("ACCEPTED","COMPLETED","FAILED","TIMED_OUT"):
            return deny("invalid_decision_or_status")
        if not all(type(o[f]) is int for o,f in ((a,"issued_at_ms"),(a,"expires_at_ms"),(e,"recorded_at_ms"))):
            return deny("invalid_timestamp")
        now = int(time.time() * 1000) if now_ms is None else now_ms
        if type(now) is not int:
            return deny("invalid_timestamp")
        if (a["issued_at_ms"] > now + 30_000 or a["expires_at_ms"] <= a["issued_at_ms"] or
            a["expires_at_ms"] - a["issued_at_ms"] > MAX_WINDOW_MS or
            now > a["expires_at_ms"] + MAX_WINDOW_MS or
            e["recorded_at_ms"] < a["issued_at_ms"] or
            e["recorded_at_ms"] > a["expires_at_ms"] or
            e["recorded_at_ms"] > now + 30_000):
            return deny("expired_or_inconsistent_timestamps")
        if e["decision_id"] != a["decision_id"] or e["action_id"] != a["action_id"]:
            return deny("identity_mismatch")
        authorization_digest = _digest(a)
        if e["authorization_digest"] != authorization_digest:
            return deny("authorization_digest_mismatch")
        if a["signer_id"] == e["signer_id"]:
            return deny("distinct_signers_required")
        if set(trusted_keys) != {"policy","executor"}:
            return deny("trusted_keys_required")
        p, x = trusted_keys["policy"], trusted_keys["executor"]
        if not isinstance(p, dict) or not isinstance(x, dict):
            return deny("trusted_keys_required")
        if set(p) != {"signer_id","public_key"} or set(x) != {"signer_id","public_key"}:
            return deny("trusted_keys_required")
        if p["signer_id"] != a["signer_id"] or x["signer_id"] != e["signer_id"]:
            return deny("untrusted_signer")
        if p["public_key"] == x["public_key"]:
            return deny("independent_keys_required")
        _verify(a, p["public_key"])
        _verify(e, x["public_key"])
        complete = a["decision"] == "ALLOW" and e["status"] == "COMPLETED"
        return {"verified": True, "authorized_and_completed": complete,
                "decision": a["decision"], "execution_status": e["status"],
                "authorization_digest": authorization_digest,
                "acknowledgment_digest": _digest(e),
                "reason": "authorized_execution_evidenced" if complete else "no_completed_authorized_execution",
                "trust_note": "Valid signatures against caller-supplied pinned keys; independently validate signer ownership and actual execution.",
                "storage": "none"}
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return deny("malformed_input_or_invalid_signature")
    except Exception:
        return deny("verification_failed")
