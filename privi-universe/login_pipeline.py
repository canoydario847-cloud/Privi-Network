"""Closed-by-default OIDC login pipeline combining Privi Universe components.

This is a library, NOT a public login endpoint. Only a future verified provider
configuration and audited HTTP adapter may call it. It never issues Pro access.

Injected adapters are server-owned only. Never accept these functions, config,
state store or claim values from an HTTP client. A real deployment needs
provider discovery, client authentication as required, shared atomic session
storage, rate-limits, logout, refresh and revocation before exposing routes.
"""
from __future__ import annotations

from account_access import AccessDenied, fetch_keys, verify_account_token
from oauth_flow import MAX_ACCESS_TOKEN, MAX_CODE, https_token_post, validate_flow_config
from oidc_identity import verify_id_token

MAX_ID_TOKEN = 12288


def complete_verified_login(
    config, transaction_store, session_store, *, state, code, oauth_config,
    id_token_jwks_uri, post_token=None, get_jwks=None,
    verify_access=None, verify_identity=None, now=None
):
    """Consume single-use state; verify BOTH signed tokens; issue session LAST.

    Never returns raw tokens, code verifier or nonce. Failures consume state
    so a callback cannot be replayed. Call only from a trusted future handler.
    """
    cfg = validate_flow_config(config)
    if not isinstance(oauth_config, dict):
        raise AccessDenied("Trusted verifier configuration required")
    if (not isinstance(id_token_jwks_uri, str) or
            not id_token_jwks_uri.startswith("https://") or
            id_token_jwks_uri != oauth_config.get("PRIVI_UNIVERSE_OAUTH_JWKS")):
        raise AccessDenied("Pinned ID-token JWKS required")
    if cfg["issuer"] != oauth_config.get("PRIVI_UNIVERSE_OAUTH_ISSUER"):
        raise AccessDenied("Issuer configuration mismatch")
    if not isinstance(code, str) or not 1 <= len(code) <= MAX_CODE or any(
        ord(char) < 33 or ord(char) > 126 for char in code
    ):
        raise AccessDenied("Invalid authorization code")
    try:
        transaction = transaction_store.consume(
            state, issuer=cfg["issuer"], redirect_uri=cfg["redirect_uri"])
    except ValueError as exc:
        raise AccessDenied("Invalid, expired or replayed state") from exc

    post = post_token or https_token_post
    reply = post(cfg["token_endpoint"], {
        "grant_type": "authorization_code", "code": code,
        "client_id": cfg["client_id"], "redirect_uri": cfg["redirect_uri"],
        "code_verifier": transaction["code_verifier"],
    })
    if not isinstance(reply, dict) or reply.get("token_type") != "Bearer":
        raise AccessDenied("Invalid bearer exchange")
    access_token, id_token = reply.get("access_token"), reply.get("id_token")
    if (not isinstance(access_token, str) or not access_token or
            len(access_token) > MAX_ACCESS_TOKEN or
            not isinstance(id_token, str) or not id_token or len(id_token) > MAX_ID_TOKEN):
        raise AccessDenied("Both OAuth access and OIDC ID tokens required")
    access_verifier = verify_access or verify_account_token
    access_claims = access_verifier(access_token, oauth_config)
    if not isinstance(access_claims, dict) or not isinstance(access_claims.get("sub"), str):
        raise AccessDenied("Invalid verified account")
    id_verifier = verify_identity or verify_id_token
    jwks_loader = get_jwks or fetch_keys
    id_claims = id_verifier(
        id_token, issuer=cfg["issuer"], client_id=cfg["client_id"],
        expected_nonce=transaction["nonce"], access_token=access_token,
        jwks=jwks_loader(id_token_jwks_uri), now=now,
    )
    if (not isinstance(id_claims, dict) or
            id_claims.get("oidc_identity_verified") is not True or
            id_claims.get("sub") != access_claims["sub"] or
            id_claims.get("issuer") != cfg["issuer"]):
        raise AccessDenied("Identity and access-token subjects disagree")
    import time
    timestamp = int(time.time()) if now is None else now
    issued = session_store.issue(subject=id_claims["sub"],
                                 issuer=cfg["issuer"], auth_time=timestamp)
    return {"account_verified": True, "subject": id_claims["sub"],
            "session": issued, "pro_access": "NOT_GRANTED",
            "id_token": "NOT_RETURNED", "access_token": "NOT_RETURNED"}
