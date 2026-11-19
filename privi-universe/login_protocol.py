"""Privi Universe OAuth 2.1 authorization-code PKCE transaction protection.

Prelaunch library only. Does not send users to an IdP, exchange authorization
codes, issue login cookies, create accounts, or grant paid access.

Use only with a trusted configured identity provider and a separately verified
authorization-code token exchange. This prototype's in-memory transaction store
is intentionally NOT production durable or distributed.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import secrets
import threading
import time

TTL_SECONDS = 300
MAX_PENDING = 128


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def s256_challenge(verifier: str) -> str:
    if not isinstance(verifier, str) or not 43 <= len(verifier) <= 128:
        raise ValueError("PKCE verifier length must be 43-128")
    if any(not (c.isascii() and (c.isalnum() or c in "-._~")) for c in verifier):
        raise ValueError("PKCE verifier contains prohibited characters")
    return b64(hashlib.sha256(verifier.encode("ascii")).digest())


class LoginTransactions:
    """Single-use, short-lived state that binds issuer and redirect URI.

    This protects pending login state, NOT an existing authenticated session.
    Never expose code_verifier or nonce to an untrusted caller.
    """
    def __init__(self, now=None):
        self.now = now or time.time
        self.lock = threading.RLock()
        self.pending = {}

    def issue(self, *, issuer, redirect_uri):
        if not isinstance(issuer, str) or not issuer.startswith("https://"):
            raise ValueError("HTTPS issuer required")
        if not isinstance(redirect_uri, str) or not redirect_uri.startswith("https://"):
            raise ValueError("Registered HTTPS redirect URI required")
        if "@" in redirect_uri.split("/")[2] or "#" in redirect_uri:
            raise ValueError("Invalid redirect URI")
        with self.lock:
            timestamp = self.now()
            self.pending = {key: record for key, record in self.pending.items()
                            if record["expires"] > timestamp}
            if len(self.pending) >= MAX_PENDING:
                raise RuntimeError("Too many pending login transactions")
            verifier = b64(secrets.token_bytes(48))
            state = b64(secrets.token_bytes(32))
            nonce = b64(secrets.token_bytes(24))
            self.pending[hashlib.sha256(state.encode()).digest()] = {
                "verifier": verifier, "nonce": nonce, "issuer": issuer,
                "redirect_uri": redirect_uri, "expires": timestamp + TTL_SECONDS,
            }
        return {"state": state, "nonce": nonce, "code_challenge": s256_challenge(verifier),
                "code_challenge_method": "S256", "expires_in_seconds": TTL_SECONDS}

    def consume(self, state, *, issuer, redirect_uri):
        """Consume even a mismatched attempt; never allow state replay."""
        if not isinstance(state, str) or not 20 <= len(state) <= 256:
            raise ValueError("Invalid OAuth state")
        key = hashlib.sha256(state.encode("utf-8")).digest()
        with self.lock:
            record = self.pending.pop(key, None)
        if record is None:
            raise ValueError("Unknown or replayed OAuth state")
        if record["expires"] <= self.now():
            raise ValueError("Expired OAuth state")
        if (not hmac.compare_digest(record["issuer"], issuer)
                or not hmac.compare_digest(record["redirect_uri"], redirect_uri)):
            raise ValueError("Issuer or redirect mismatch")
        return {"code_verifier": record["verifier"], "nonce": record["nonce"]}
