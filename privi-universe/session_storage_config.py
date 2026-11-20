"""Privi Universe dedicated session-storage deployment preflight.

This module never connects to a database or reads users. It checks whether
a *separate* postgres session database has been explicitly configured, and
prevents accidental reuse of Privi billing's staging/production databases.

Preflight success is NOT proof that a DB exists, is persistent, supports
transactions, has backups, or is safe for user sessions. No public login is
activated by configuration values.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit, parse_qsl, unquote

# Do not put actual credentials or connection strings in source or telemetry.
PROHIBITED_DB_NAMES = frozenset({
    "privi_billing_staging", "privi_billing_production",
})
PROHIBITED_DB_SUBSTRINGS = ("billing", "stripe", "payment", "ledger")
REQUIRED_SCHEMA = "privi_sessions"


def check_session_storage(config=None):
    """Return only redacted boolean/error codes; never return URLs or secrets."""
    cfg = dict(os.environ) if config is None else config
    if cfg.get("PRIVI_UNIVERSE_SESSION_BACKEND") != "postgres":
        return {"ready":False,"reason":"session_backend_not_enabled"}
    uri = cfg.get("PRIVI_UNIVERSE_SESSION_DATABASE_URL", "")
    if not isinstance(uri, str) or not uri or len(uri) > 2048:
        return {"ready":False,"reason":"dedicated_database_url_missing"}
    try:
        parsed = urlsplit(uri)
        dbname = unquote(parsed.path.lstrip("/")).lower()
        params = dict(parse_qsl(parsed.query,keep_blank_values=True))
        host = parsed.hostname
        port = parsed.port
    except (ValueError, TypeError):
        return {"ready":False,"reason":"invalid_database_configuration"}
    if (parsed.scheme not in ("postgresql","postgres")
            or not host or parsed.fragment or parsed.username is None
            or parsed.password is None or not parsed.password or not dbname
            or "/" in dbname or port == 0):
        return {"ready":False,"reason":"invalid_database_configuration"}
    if (dbname in PROHIBITED_DB_NAMES
            or any(part in dbname for part in PROHIBITED_DB_SUBSTRINGS)):
        return {"ready":False,"reason":"billing_database_is_not_session_storage"}
    if params.get("sslmode") != "verify-full":
        return {"ready":False,"reason":"tls_identity_verification_required"}
    if any(k not in ("sslmode", "sslrootcert") for k in params):
        return {"ready":False,"reason":"unsupported_connection_options"}
    if cfg.get("PRIVI_UNIVERSE_SESSION_SCHEMA") != REQUIRED_SCHEMA:
        return {"ready":False,"reason":"dedicated_session_schema_required"}
    if cfg.get("PRIVI_UNIVERSE_SESSION_ADMIN_REVIEWED") != "true":
        return {"ready":False,"reason":"admin_review_missing"}
    if cfg.get("PRIVI_UNIVERSE_SESSION_BACKUPS_VERIFIED") != "true":
        return {"ready":False,"reason":"backup_verification_missing"}
    return {"ready":True,"reason":"configuration_present_unverified_connectivity"}
