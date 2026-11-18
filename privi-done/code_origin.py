"""Privi Code Origin: compare recorded human/agent code contributions.

Authorship cannot be detected reliably from source style or Git commit labels.
An unverified manifest is a CLAIM. A pinned-key authenticated manifest can
establish who signed a claim, but cannot independently prove who typed code.
This offline module is not a forensic AI-code classifier.
"""
import hashlib
import hmac
import json

CATEGORIES = {"human", "agent"}
MAX_LINES = 100_000


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _lines_digest(lines):
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def verify_attestation(manifest, pinned_keys):
    """Verify test HMAC claim integrity with externally pinned fixture keys.

    Real deployments should use protected asymmetric keys and independent
    identity enrollment. HMAC proves only possession of the shared key.
    """
    if not isinstance(manifest, dict) or not isinstance(pinned_keys, dict):
        return False
    if set(manifest) != {"file_sha256", "line_count", "ranges",
                         "signer_id", "signature_hmac_sha256"}:
        return False
    signer = manifest["signer_id"]
    key = pinned_keys.get(signer) if isinstance(signer, str) else None
    sig = manifest["signature_hmac_sha256"]
    if not isinstance(key, bytes) or len(key) < 32 or not isinstance(sig, str):
        return False
    try:
        body = {k: v for k, v in manifest.items() if k != "signature_hmac_sha256"}
        expected = hmac.new(key, b"PRIVI-CODE-ORIGIN-CLAIM-v1\x00" + _canonical(body),
                            hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except (TypeError, ValueError, OverflowError):
        return False


def compare_code(source, manifest=None, *, pinned_keys=None):
    """Return line spans and recorded category; missing proof remains unknown.

    Do not upload sensitive source to unknown servers. Only supplied source
    bytes and line-range attestations are used. Does not infer authorship.
    """
    if not isinstance(source, str) or "\x00" in source:
        raise ValueError("source must be UTF-8 text without NUL")
    lines = source.splitlines()
    if len(lines) > MAX_LINES:
        raise ValueError("too many source lines")
    file_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    result = {
        "schema": "privi-code-origin-v1",
        "file_sha256": file_sha,
        "total_lines": len(lines),
        "attribution": "UNKNOWN",
        "evidence": "NO_VERIFIED_AUTHORSHIP_EVIDENCE",
        "lines": [{"number": i + 1, "category": "unknown"} for i in range(len(lines))],
        "counts": {"human": 0, "agent": 0, "unknown": len(lines)},
    }
    if manifest is None:
        return result
    if not isinstance(manifest, dict) or not verify_attestation(manifest, pinned_keys):
        return result
    if manifest["file_sha256"] != file_sha or type(manifest["line_count"]) is not int or manifest["line_count"] != len(lines):
        return result
    ranges = manifest["ranges"]
    if not isinstance(ranges, list):
        return result
    assignments = ["unknown"] * len(lines)
    try:
        for item in ranges:
            if not isinstance(item, dict) or set(item) != {"start", "end", "category", "span_sha256"}:
                return result
            start, end, category, claimed_digest = (item["start"], item["end"],
                                                   item["category"], item["span_sha256"])
            if (type(start) is not int or type(end) is not int
                    or not 1 <= start <= end <= len(lines) or category not in CATEGORIES
                    or not isinstance(claimed_digest, str)
                    or not hmac.compare_digest(claimed_digest,
                                               _lines_digest(lines[start - 1:end]))):
                return result
            if any(assignments[i] != "unknown" for i in range(start - 1, end)):
                return result
            for i in range(start - 1, end):
                assignments[i] = category
    except (TypeError, ValueError):
        return result
    counts = {name: assignments.count(name) for name in ("human", "agent", "unknown")}
    covered = [name for name in ("human", "agent") if counts[name]]
    attribution = "MIXED" if len(covered) == 2 else (covered[0].upper() if covered else "UNKNOWN")
    return {**result, "attribution": attribution,
            "evidence": "SIGNED_CLAIMS_NOT_INDEPENDENT_AUTHORSHIP_PROOF",
            "lines": [{"number": i + 1, "category": name} for i, name in enumerate(assignments)],
            "counts": counts}


def make_test_attestation(source, ranges, signer_id, key):
    """Fixture helper. Never use a shared-key fixture as production provenance."""
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("test key must be at least 32 bytes")
    lines = source.splitlines()
    claims = []
    for start, end, category in ranges:
        if (type(start) is not int or type(end) is not int or
                not 1 <= start <= end <= len(lines) or category not in CATEGORIES):
            raise ValueError("invalid test range")
        claims.append({"start": start, "end": end, "category": category,
                       "span_sha256": _lines_digest(lines[start - 1:end])})
    body = {"file_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "line_count": len(lines), "ranges": claims, "signer_id": signer_id}
    body["signature_hmac_sha256"] = hmac.new(
        key, b"PRIVI-CODE-ORIGIN-CLAIM-v1\x00" + _canonical(body),
        hashlib.sha256).hexdigest()
    return body
