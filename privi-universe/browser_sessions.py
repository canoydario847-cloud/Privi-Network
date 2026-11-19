"""Privi Universe prelaunch server-side browser session security primitives.

NOT wired to public HTTP routes: no users can sign in or receive sessions.
In-memory only; not suitable for production multi-instance deployments.
Create sessions ONLY following verified OIDC ID token, correct PKCE/state
and independently authenticated token exchange. A session is NEVER Pro proof.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

SESSION_SECONDS = 1800
MAX_SESSIONS = 200
COOKIE_NAME = "__Host-privi_session"
TOKEN_BYTES = 32
CSRF_BYTES = 32


class SessionDenied(Exception):
    pass


def _token_hash(value):
    if not isinstance(value, str) or len(value) != 43 or any(
        c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in value
    ):
        raise SessionDenied("Invalid session handle")
    return hashlib.sha256(value.encode("ascii")).digest()


def _safe_origin(origin, expected):
    if not isinstance(origin, str) or not isinstance(expected, str):
        return False
    a, b = urlsplit(origin), urlsplit(expected)
    if a.scheme != "https" or b.scheme != "https":
        return False
    if a.username or a.password or a.query or a.fragment or a.path not in ("", "/"):
        return False
    if b.username or b.password or b.query or b.fragment or b.path not in ("", "/"):
        return False
    return hmac.compare_digest(origin.rstrip("/"), expected.rstrip("/"))


def cookie_header(session_handle):
    _token_hash(session_handle)
    # __Host- cookie: Secure, Path=/, no Domain. Never set browser JS access.
    return (
        f"{COOKIE_NAME}={session_handle}; Path=/; Max-Age={SESSION_SECONDS}; "
        "HttpOnly; Secure; SameSite=Lax"
    )


def clear_cookie_header():
    return f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax"


def extract_cookie(header):
    """Read exactly one valid cookie; reject ambiguity and oversized input."""
    if not isinstance(header, str) or not header or len(header) > 4096:
        raise SessionDenied("Missing or invalid cookie header")
    # Reject duplicates before parser normalization.
    names = [part.split("=", 1)[0].strip() for part in header.split(";") if "=" in part]
    if names.count(COOKIE_NAME) != 1:
        raise SessionDenied("Missing or duplicate session cookie")
    parsed = SimpleCookie()
    try:
        parsed.load(header)
    except Exception as exc:
        raise SessionDenied("Malformed cookie") from exc
    item = parsed.get(COOKIE_NAME)
    if item is None:
        raise SessionDenied("Missing session cookie")
    token = item.value
    _token_hash(token)
    return token


class SessionStore:
    def __init__(self, *, now=None):
        self._now = now if now is not None else time.time
        self._items = {}
        self._lock = threading.RLock()

    def _purge(self, now):
        self._items = {k: row for k, row in self._items.items() if row["expires"] > now}

    def issue(self, *, subject, issuer, auth_time):
        """Server-only. Subject is from verified identity, never browser input."""
        if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
            raise SessionDenied("Invalid verified subject")
        if not isinstance(issuer, str) or not issuer.startswith("https://"):
            raise SessionDenied("Invalid verified issuer")
        now = self._now()
        if not isinstance(auth_time, (int, float)) or isinstance(auth_time, bool):
            raise SessionDenied("Invalid authentication time")
        if auth_time > now + 45 or auth_time < now - 300:
            raise SessionDenied("Stale or future authentication")
        session = secrets.token_urlsafe(TOKEN_BYTES)
        csrf = secrets.token_urlsafe(CSRF_BYTES)
        key = _token_hash(session)
        with self._lock:
            self._purge(now)
            if len(self._items) >= MAX_SESSIONS:
                raise SessionDenied("Session capacity reached")
            self._items[key] = {
                "subject": subject, "issuer": issuer, "auth_time": auth_time,
                "expires": now + SESSION_SECONDS, "csrf_hash": hashlib.sha256(csrf.encode()).digest()
            }
        return {"session_handle": session, "csrf_token": csrf, "expires_in": SESSION_SECONDS,
                "cookie": cookie_header(session), "access": "ACCOUNT_ONLY_NO_PRO"}

    def validate(self, session_handle):
        key = _token_hash(session_handle)
        with self._lock:
            now = self._now()
            record = self._items.get(key)
            if not record:
                raise SessionDenied("No session")
            if record["expires"] <= now:
                del self._items[key]
                raise SessionDenied("Session expired")
            return {"subject": record["subject"], "issuer": record["issuer"],
                    "auth_time": record["auth_time"], "expires_at": record["expires"],
                    "pro_access": False}

    def require_csrf(self, session_handle, *, csrf_token, origin, expected_origin):
        key = _token_hash(session_handle)
        if not _safe_origin(origin, expected_origin):
            raise SessionDenied("Invalid request origin")
        if not isinstance(csrf_token, str) or not 32 <= len(csrf_token) <= 128:
            raise SessionDenied("Missing anti-CSRF token")
        supplied_hash = hashlib.sha256(csrf_token.encode("utf-8")).digest()
        with self._lock:
            self.validate(session_handle)
            row = self._items.get(key)
            if row is None or not hmac.compare_digest(row["csrf_hash"], supplied_hash):
                raise SessionDenied("CSRF verification failed")
            return True

    def revoke(self, session_handle, *, csrf_token, origin, expected_origin):
        """Log out only with valid session, CSRF token and same HTTPS origin."""
        self.require_csrf(session_handle, csrf_token=csrf_token,
                          origin=origin, expected_origin=expected_origin)
        key = _token_hash(session_handle)
        with self._lock:
            if self._items.pop(key, None) is None:
                raise SessionDenied("Session already revoked")
        return clear_cookie_header()

    def revoke_subject(self, *, subject, issuer):
        """Trusted server-only revocation hook for upstream logout events."""
        if not subject or not issuer:
            raise SessionDenied("Verified subject and issuer required")
        with self._lock:
            matching = [key for key, row in self._items.items()
                        if row["subject"] == subject and row["issuer"] == issuer]
            for key in matching:
                del self._items[key]
            return len(matching)
