"""Privi Agent Execution Evidence v0.1: offline, stdlib-only receipt verifier.

This is a research prototype. It does not assert that an action actually happened:
execution evidence must be independently attested by the target system.
"""
import hashlib
import hmac
import json
from datetime import datetime, timezone

REQUIRED = ("tenant", "agent_id", "request_id", "policy_version", "software_digest",
            "action", "authorization", "execution", "timestamp", "previous_hash")
ALLOWED_AUTH = {"approved", "denied"}
ALLOWED_EXEC = {"not_attempted", "reported_success", "reported_failure", "verified_success", "verified_failure"}

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def receipt_hash(receipt):
    return hashlib.sha256(canonical(receipt)).hexdigest()

def issue_receipt(event, secret, prior_hash="0"*64):
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("HMAC key must be at least 32 bytes")
    receipt = dict(event)
    receipt["previous_hash"] = prior_hash
    receipt.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    errors = validate(receipt)
    if errors:
        raise ValueError("; ".join(errors))
    signature = hmac.new(secret, canonical(receipt), hashlib.sha256).hexdigest()
    return {"receipt": receipt, "signature": signature, "algorithm": "HMAC-SHA256"}

def validate(r):
    if not isinstance(r, dict):
        return ["receipt must be an object"]
    errors = [f"missing {k}" for k in REQUIRED if not isinstance(r.get(k), str) or not r[k]]
    if r.get("authorization") not in ALLOWED_AUTH:
        errors.append("invalid authorization")
    if r.get("execution") not in ALLOWED_EXEC:
        errors.append("invalid execution")
    if r.get("authorization") == "denied" and r.get("execution") != "not_attempted":
        errors.append("denied action cannot claim execution")
    if r.get("execution", "").startswith("verified_") and not r.get("external_attestation"):
        errors.append("verified outcome requires external_attestation")
    if not isinstance(r.get("previous_hash"), str) or len(r["previous_hash"]) != 64 or any(c not in "0123456789abcdef" for c in r["previous_hash"]):
        errors.append("invalid previous_hash")
    return errors

def verify(envelope, secret, expected_previous_hash=None):
    if not isinstance(envelope, dict) or envelope.get("algorithm") != "HMAC-SHA256":
        return False
    receipt = envelope.get("receipt")
    if validate(receipt):
        return False
    if expected_previous_hash is not None and receipt["previous_hash"] != expected_previous_hash:
        return False
    signature = envelope.get("signature")
    if not isinstance(signature, str):
        return False
    return hmac.compare_digest(hmac.new(secret, canonical(receipt), hashlib.sha256).hexdigest(), signature)

def verify_chain(envelopes, secret):
    previous = "0"*64
    seen = set()
    for envelope in envelopes:
        if not verify(envelope, secret, previous):
            return False
        request_id = (envelope["receipt"]["tenant"], envelope["receipt"]["request_id"])
        if request_id in seen:
            return False
        seen.add(request_id)
        previous = receipt_hash(envelope["receipt"])
    return True
