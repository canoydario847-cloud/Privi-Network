#!/usr/bin/env python3
"""Fail-closed, read-only JSON evidence loader for Privi financial launch review.

This is input hygiene, NOT a third-party audit, signature verifier, or GO
decision. Reject duplicate JSON properties and obvious secret material
without printing any of the offending values into logs.
"""
import json
import re
from pathlib import Path

# Key names are checked in normalized form so common aliases like
# apiKey, rootPassword and walletSeed are not overlooked. Public-key
# fingerprints are allowed; never confuse them with signing private keys.
_FORBIDDEN_FIELD = re.compile(
    r"privatekey|password|passwd|secret|mnemonic|seedphrase|"
    r"recoveryphrase|apikey|accesstoken|refreshtoken|walletseed|"
    r"authorizationheader|jwttoken|bearertoken|credential", re.I
)
_FORBIDDEN_VALUE = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----|"
    r"-----BEGIN OPENSSH PRIVATE KEY-----|"
    r"\bsk-proj-[A-Za-z0-9_-]{15,}|"
    r"\bghp_[A-Za-z0-9]{20,}|"
    r"\bgithub_pat_[A-Za-z0-9_]{20,}|"
    r"\bxox[baprs]-[A-Za-z0-9-]{16,}|"
    r"\bAKIA[0-9A-Z]{16}", re.I
)

def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property is forbidden (name intentionally withheld)")
        result[key] = value
    return result

def load(path: Path):
    """Strict duplicate-free JSON, UTF-8 only, no filesystem modifications."""
    try:
        result = json.loads(Path(path).read_text(encoding="utf-8"),
                            object_pairs_hook=_unique_pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(
                                ValueError("nonfinite JSON numeric value forbidden")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid UTF-8 JSON evidence") from exc
    reject_secrets(result)
    return result

def reject_secrets(value, location="root"):
    """Recursively reject known credential fields or values, redacting data."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(location + ": JSON field names must be text")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if _FORBIDDEN_FIELD.search(normalized):
                raise ValueError(location + ": prohibited credential-like JSON field")
            # Never echo user-controlled field names (which may contain a
            # credential themselves) into build logs or exception reports.
            reject_secrets(item, location + ".object")
    elif isinstance(value, list):
        for element in value:
            reject_secrets(element, location + "[]")
    elif isinstance(value, str):
        if _FORBIDDEN_VALUE.search(value):
            raise ValueError(location + ": probable sensitive credential value")
