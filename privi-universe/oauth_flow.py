"""Privi Universe opt-in OAuth 2.1 code exchange foundation (offline-tested).

NOT exposed via public HTTP endpoints. The flow requires a preconfigured,
trusted issuer and pre-registered absolute URLs. It does not create sessions,
set cookies, register users, or grant billing entitlements.

In production require explicit IdP selection, exact redirect allowlisting,
client authentication as applicable, independently audited token endpoints,
trusted session storage and cookie/CSRF protections before enabling login.
"""
from __future__ import annotations

import json
import re
import ssl
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

from login_protocol import LoginTransactions
from account_access import AccessDenied, verify_account_token

MAX_RESPONSE = 16384
MAX_CODE = 2048
MAX_ACCESS_TOKEN = 12288
CLIENT_ID = re.compile(r"^[A-Za-z0-9._~-]{1,200}$")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AccessDenied("Unexpected OAuth endpoint redirect")


def secure_url(url):
    if not isinstance(url, str) or len(url) > 1024:
        return False
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and bool(parsed.hostname) and
            parsed.username is None and parsed.password is None and
            parsed.fragment == "" and parsed.query == "")


def validate_flow_config(config):
    """Only explicitly configured, pinned IdP URLs are accepted."""
    if not isinstance(config, dict):
        raise AccessDenied("OIDC configuration required")
    fields = ("issuer", "authorization_endpoint", "token_endpoint",
              "redirect_uri", "client_id")
    if any(not config.get(field) for field in fields):
        raise AccessDenied("Missing OAuth flow settings")
    if not all(secure_url(config[field]) for field in fields[:4]):
        raise AccessDenied("HTTPS IdP and redirect URLs required")
    if not CLIENT_ID.fullmatch(config["client_id"]):
        raise AccessDenied("Invalid OAuth client identifier")
    issuer_host = urlsplit(config["issuer"]).hostname
    if urlsplit(config["authorization_endpoint"]).hostname != issuer_host or (
        urlsplit(config["token_endpoint"]).hostname != issuer_host
    ):
        raise AccessDenied("Endpoints must share configured issuer host")
    if urlsplit(config["redirect_uri"]).path != "/oauth/callback":
        raise AccessDenied("Unexpected registered callback path")
    return config


def authorization_request(config, store):
    cfg = validate_flow_config(config)
    tx = store.issue(issuer=cfg["issuer"], redirect_uri=cfg["redirect_uri"])
    params = {
        "response_type": "code", "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"], "scope": "openid privi:account",
        "state": tx["state"], "nonce": tx["nonce"],
        "code_challenge": tx["code_challenge"],
        "code_challenge_method": "S256",
    }
    # Do not return the private code verifier to the browser.
    return {"url": cfg["authorization_endpoint"] + "?" + urlencode(params),
            "state": tx["state"], "expires_in_seconds": tx["expires_in_seconds"]}


def https_token_post(url, body):
    if not secure_url(url):
        raise AccessDenied("Invalid token endpoint")
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    data = urlencode(body).encode("utf-8")
    req = Request(url, data=data, method="POST", headers={
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "PriviUniverseOAuthSandbox/1",
    })
    try:
        with opener.open(req, timeout=8) as response:
            if response.status != 200:
                raise AccessDenied("Token exchange failed")
            raw = response.read(MAX_RESPONSE + 1)
    except (OSError, TimeoutError, ValueError) as exc:
        raise AccessDenied("Token endpoint unavailable") from exc
    if len(raw) > MAX_RESPONSE:
        raise AccessDenied("Token response too large")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise AccessDenied("Malformed token response") from exc
    if not isinstance(data, dict):
        raise AccessDenied("Invalid token response")
    return data


def finish_code_exchange(
    config, store, *, state, code, auth_config, token_post=None,
    validate_access_token=verify_account_token
):
    """Consume single-use PKCE transaction, POST exchange, verify JWT.

    The access token is intentionally NOT returned, stored or issued as a
    session cookie. This is a testable back-end integration precursor only.
    """
    cfg = validate_flow_config(config)
    if not isinstance(code, str) or not 1 <= len(code) <= MAX_CODE or any(
        ord(c) < 33 or ord(c) > 126 for c in code
    ):
        raise AccessDenied("Invalid authorization code")
    try:
        tx = store.consume(state, issuer=cfg["issuer"], redirect_uri=cfg["redirect_uri"])
    except ValueError as exc:
        raise AccessDenied("Invalid or replayed OAuth callback") from exc
    post = token_post or https_token_post
    body = {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": cfg["redirect_uri"], "client_id": cfg["client_id"],
        "code_verifier": tx["code_verifier"],
    }
    response = post(cfg["token_endpoint"], body)
    if not isinstance(response, dict) or response.get("token_type") != "Bearer":
        raise AccessDenied("Expected bearer access-token response")
    token = response.get("access_token")
    if not isinstance(token, str) or len(token) > MAX_ACCESS_TOKEN:
        raise AccessDenied("Missing access token")
    # Never accept only an ID token, claims supplied by the browser,
    # or a self-reported premium subscription.
    account = validate_access_token(token, auth_config)
    return {"subject": account["sub"], "verified_access_token": True,
            "browser_session": "NOT_ISSUED", "pro_access": "NOT_GRANTED"}
