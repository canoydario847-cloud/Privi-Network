"""Privi ONE synthetic quote integrity (prelaunch, stdlib-only).

A short-lived server-authenticated QUOTE BUNDLE prevents accidental substitution
of prices inside the sandbox workflow. This is *not* an external provider quote,
not price discovery, and is NOT independently signed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time


SCHEMA = "privi-one-synthetic-quotes-v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")



def valid_options(options):
    """Minimal bounded schema for synthetic quotes; NOT provider authentication."""
    if not isinstance(options, list) or not 1 <= len(options) <= 32:
        return False
    seen = set()
    for item in options:
        if not isinstance(item, dict):
            return False
        if not {"id", "cost_cents", "quality", "reliability", "latency_ms"} <= set(item):
            return False
        ident = item["id"]
        if (not isinstance(ident, str) or not 1 <= len(ident) <= 80
                or ident in seen):
            return False
        seen.add(ident)
        if "name" in item and (not isinstance(item["name"], str) or len(item["name"]) > 200):
            return False
        if any(type(item[k]) is not int for k in
               ("cost_cents", "quality", "reliability", "latency_ms")):
            return False
        if not (0 <= item["cost_cents"] <= 100_000_000
                and 0 <= item["quality"] <= 100
                and 0 <= item["reliability"] <= 100
                and 0 <= item["latency_ms"] <= 3_600_000):
            return False
    return True


def issue(options, task_sha256, *, key, now=None, ttl_seconds=120):
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("Server quote authentication key missing")
    if (not isinstance(task_sha256, str) or len(task_sha256) != 64
            or any(x not in "0123456789abcdef" for x in task_sha256)):
        raise ValueError("Invalid task fingerprint")
    if not valid_options(options):
        raise ValueError("Invalid synthetic quote options")
    if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 600:
        raise ValueError("Invalid quote lifetime")
    now = int(time.time()) if now is None else now
    body = {"schema": SCHEMA, "issuer": "PRIVI_ONE_LOCAL_SIMULATION",
            "task_sha256": task_sha256, "issued_at": now,
            "expires_at": now + ttl_seconds, "options": options}
    mac = hmac.new(key, canonical(body), hashlib.sha256).hexdigest()
    return {"body": body, "auth": {"algorithm": "HMAC-SHA256-LOCAL-ONLY", "mac": mac}}


def verify(bundle, task_sha256, *, key, now=None):
    if not isinstance(key, bytes) or len(key) < 32 or not isinstance(bundle, dict):
        return False
    body, auth = bundle.get("body"), bundle.get("auth")
    if not isinstance(body, dict) or not isinstance(auth, dict):
        return False
    if body.get("schema") != SCHEMA or body.get("issuer") != "PRIVI_ONE_LOCAL_SIMULATION":
        return False
    if body.get("task_sha256") != task_sha256 or not isinstance(task_sha256, str):
        return False
    issued, expires = body.get("issued_at"), body.get("expires_at")
    now = int(time.time()) if now is None else now
    if any(type(v) is not int for v in (issued, expires, now)):
        return False
    if issued > now or expires < now or expires - issued > 600 or expires <= issued:
        return False
    if auth.get("algorithm") != "HMAC-SHA256-LOCAL-ONLY":
        return False
    if (not valid_options(body.get("options"))
            or not isinstance(task_sha256, str) or len(task_sha256) != 64
            or any(x not in "0123456789abcdef" for x in task_sha256)):
        return False
    try:
        expected = hmac.new(key, canonical(body), hashlib.sha256).hexdigest()
    except (ValueError, TypeError, OverflowError):
        return False
    return hmac.compare_digest(expected, str(auth.get("mac", "")))
