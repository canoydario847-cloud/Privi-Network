"""Isolated anonymous sandbox identity + retry-safe receipt cache.

A self-issued sandbox session is NOT user authentication and grants no entitlement.
Records are in-memory, process-local and intentionally short-lived; no payment,
provider call, Ledger write or token is performed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import OrderedDict

TTL_SECONDS = 900
MAX_RECEIPTS = 256


def _bytes(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SandboxIdentity:
    def __init__(self, key: bytes):
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("Sandbox session key must be 32 bytes or longer")
        self._key = key

    def issue(self, *, now=None):
        now = int(time.time()) if now is None else now
        claims = {"mode": "ANONYMOUS_SANDBOX_NOT_REAL_AUTH", "sid": secrets.token_hex(16),
                  "iat": now, "exp": now + TTL_SECONDS}
        body = _b64(_bytes(claims))
        mac = _b64(hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest())
        return {"token": body + "." + mac, "expires_at": claims["exp"],
                "identity": "anonymous sandbox session"}

    def verify(self, token, *, now=None):
        now = int(time.time()) if now is None else now
        if not isinstance(token, str) or len(token) > 512 or token.count(".") != 1:
            return None
        try:
            body, mac = token.split(".", 1)
            expected = _b64(hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(mac, expected):
                return None
            claims = json.loads(_unb64(body))
            if (not isinstance(claims, dict)
                    or claims.get("mode") != "ANONYMOUS_SANDBOX_NOT_REAL_AUTH"
                    or not isinstance(claims.get("sid"), str)
                    or len(claims["sid"]) != 32
                    or any(type(claims.get(x)) is not int for x in ("iat", "exp"))
                    or claims["iat"] > now or claims["exp"] < now
                    or claims["exp"] - claims["iat"] != TTL_SECONDS):
                return None
            return claims["sid"]
        except (ValueError, TypeError, UnicodeError, OverflowError):
            return None


class RetryStore:
    """Bounded in-process idempotency, safe for concurrent requests per worker."""

    def __init__(self, max_entries=MAX_RECEIPTS):
        self._lock = threading.Lock()
        self._entries = OrderedDict()
        self._max_entries = max_entries

    def run_once(self, session_id, request_id, payload, create, *, now=None):
        if (not isinstance(session_id, str) or not session_id
                or not isinstance(request_id, str) or not 8 <= len(request_id) <= 128
                or not all(c.isascii() and (c.isalnum() or c in "-_") for c in request_id)):
            raise ValueError("Invalid sandbox session/request identifier")
        now = time.time() if now is None else now
        fingerprint = hashlib.sha256(_bytes(payload)).hexdigest()
        k = (session_id, request_id)
        # Create under the lock to ensure concurrent duplicates cannot fork a receipt.
        with self._lock:
            for existing_key in tuple(self._entries):
                if self._entries[existing_key][0] <= now:
                    self._entries.pop(existing_key, None)
            if k in self._entries:
                expiry, previous_fingerprint, result = self._entries[k]
                if not hmac.compare_digest(previous_fingerprint, fingerprint):
                    raise ValueError("Conflicting request ID replay")
                self._entries.move_to_end(k)
                return result, True
            result = create()
            self._entries[k] = (now + TTL_SECONDS, fingerprint, result)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return result, False
