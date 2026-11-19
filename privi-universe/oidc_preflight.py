"""Strict OpenID Connect configuration preflight (no customer login).

This is a pure metadata validator, not an identity provider or authorization
callback. Metadata MUST be fetched over TLS from an administrator-pinned issuer
outside a browser request. Configured URL strings alone never establish trust.
"""
from __future__ import annotations
import re
from urllib.parse import urlsplit

CLIENT_ID = re.compile(r"^[A-Za-z0-9._~:-]{5,160}$")


class PreflightError(ValueError):
    pass


def secure_url(url, *, permit_query=False):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        return False
    try:
        p = urlsplit(url)
        _ = p.port
    except ValueError:
        return False
    return (p.scheme == "https" and bool(p.hostname) and p.hostname not in
            ("localhost", "127.0.0.1", "::1") and not p.username and
            not p.password and not p.fragment and (permit_query or not p.query))


def validate_metadata(metadata, *, issuer, client_id, redirect_uri, jwks_uri,
                      expected_authorize=None, expected_token=None):
    """Check OIDC discovery data before any auth-code or token exchange.

    The two endpoint allowlist arguments, if supplied, must exactly match the
    administrator-approved HTTPS URLs; never silently follow discovery to a
    different host. An upstream fetcher must authenticate the issuer response.
    """
    if not all(secure_url(u) for u in (issuer, redirect_uri, jwks_uri)):
        raise PreflightError("Secure issuer, redirect and JWKS URLs required")
    if not isinstance(client_id, str) or not CLIENT_ID.fullmatch(client_id):
        raise PreflightError("Invalid registered OAuth client ID")
    if not isinstance(metadata, dict) or metadata.get("issuer") != issuer:
        raise PreflightError("Issuer mismatch")
    auth = metadata.get("authorization_endpoint")
    token = metadata.get("token_endpoint")
    jwks = metadata.get("jwks_uri")
    if not all(secure_url(u) for u in (auth, token, jwks)):
        raise PreflightError("Secure authorization, token and JWKS URLs required")
    if jwks != jwks_uri:
        raise PreflightError("JWKS is not the pinned key endpoint")
    if expected_authorize is not None and auth != expected_authorize:
        raise PreflightError("Authorization endpoint not approved")
    if expected_token is not None and token != expected_token:
        raise PreflightError("Token endpoint not approved")
    requirements = (("response_types_supported", "code"),
                    ("code_challenge_methods_supported", "S256"),
                    ("grant_types_supported", "authorization_code"))
    for field, required in requirements:
        values = metadata.get(field)
        if not isinstance(values, list) or required not in values:
            raise PreflightError("Required authorization-code PKCE feature unavailable")
    algorithms = metadata.get("id_token_signing_alg_values_supported")
    if not isinstance(algorithms, list) or "RS256" not in algorithms:
        raise PreflightError("Supported signature algorithm not established")
    return {"valid": True, "status": "METADATA_VALIDATED_NOT_LOGIN_ENABLED",
            "issuer": issuer, "authorization_endpoint": auth,
            "token_endpoint": token, "jwks_uri": jwks,
            "client_id": client_id, "redirect_uri": redirect_uri,
            "code_challenge_method": "S256"}


def authorization_parameters(*, transaction, client_id, redirect_uri):
    """Return only public parameters for a future authorization request.

    No code_verifier, token, signing key or session cookie is returned.
    """
    if not isinstance(transaction, dict) or not isinstance(client_id, str) or not CLIENT_ID.fullmatch(client_id):
        raise PreflightError("Invalid transaction")
    if not secure_url(redirect_uri):
        raise PreflightError("Invalid redirect")
    keys = ("state", "nonce", "code_challenge")
    if not all(isinstance(transaction.get(k), str) and 20 <= len(transaction[k]) <= 128
               for k in keys):
        raise PreflightError("Invalid OAuth transaction parameters")
    if transaction.get("code_challenge_method") != "S256":
        raise PreflightError("PKCE S256 required")
    return {"response_type": "code", "client_id": client_id,
            "redirect_uri": redirect_uri, "scope": "openid",
            "state": transaction["state"], "nonce": transaction["nonce"],
            "code_challenge": transaction["code_challenge"],
            "code_challenge_method": "S256"}
