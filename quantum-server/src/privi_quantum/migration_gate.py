# Copyright (c) 2026 Privi World Co. All rights reserved.
"""Privi Quantum: deterministic post-quantum migration gate for ledger events.

This is a POLICY and canonicalization module, not a cryptographic signature
implementation. Verification must be performed by a trusted ML-DSA verifier
before setting verified=True. No mainnet consensus changes are made here.
"""
import hashlib
import json
from dataclasses import dataclass
from typing import Any

ALLOWED_PQ = frozenset({"ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "SLH-DSA-SHA2-128s"})
LEGACY = frozenset({"Ed25519", "ECDSA", "secp256k1", "RSA"})


def canonical_event(event: dict[str, Any]) -> bytes:
    """Canonical UTF-8 JSON; reject floats/NaN to prevent ambiguous signatures."""
    def validate(obj: Any) -> None:
        if isinstance(obj, float):
            raise ValueError("floating-point event fields are prohibited")
        if obj is None or isinstance(obj, (str, bool, int)):
            return
        if isinstance(obj, list):
            for item in obj:
                validate(item)
            return
        if isinstance(obj, dict) and all(isinstance(k, str) for k in obj):
            for item in obj.values():
                validate(item)
            return
        raise ValueError("unsupported event field")
    validate(event)
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def event_digest(event: dict[str, Any]) -> str:
    return hashlib.sha256(b"privi-quantum-event-v1\x00" + canonical_event(event)).hexdigest()


@dataclass(frozen=True)
class SignatureEvidence:
    algorithm: str
    verified: bool
    signed_digest: str


def migration_gate(event: dict[str, Any], evidence: list[SignatureEvidence],
                   require_hybrid: bool = True) -> dict[str, Any]:
    """Evaluate *already verified* evidence, fail closed on unknown algorithms.

    This function cannot authenticate evidence itself. A caller must verify
    signature bytes, public keys, domain separation, and signer authorization.
    """
    digest = event_digest(event)
    valid = [e for e in evidence if e.verified and e.signed_digest == digest]
    pq = any(e.algorithm in ALLOWED_PQ for e in valid)
    classical = any(e.algorithm in LEGACY for e in valid)
    unknown = sorted({e.algorithm for e in evidence if e.algorithm not in ALLOWED_PQ | LEGACY})
    approved = pq and (classical or not require_hybrid) and not unknown
    return {
        "event_sha256": digest,
        "approved": approved,
        "post_quantum_verified": pq,
        "classical_verified": classical,
        "hybrid_required": require_hybrid,
        "unknown_algorithms": unknown,
        "reason": "policy satisfied" if approved else "missing valid signatures or unknown algorithm",
    }
