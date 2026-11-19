"""Strict prelaunch OpenID Connect ID-token verification for Privi Universe.

No HTTP routes, cookies, accounts or paid entitlements. Call only after
server-side authorization-code exchange using a trusted JWKS fetched from
the PINNED OIDC issuer configuration. OIDC ID tokens are not OAuth API access
tokens and must never authorize resource-server routes or purchases.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from urllib.parse import urlsplit

try:
    from cryptography.hazmat.primitives import hashes, padding
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.exceptions import InvalidSignature
except ImportError:
    hashes = padding = rsa = InvalidSignature = None


class IdentityRejected(Exception):
    pass


def _decode(segment, limit=12000):
    if not isinstance(segment, str) or not 1 <= len(segment) <= limit:
        raise IdentityRejected("Malformed token encoding")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in segment):
        raise IdentityRejected("Malformed token encoding")
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (ValueError, TypeError) as exc:
        raise IdentityRejected("Malformed token encoding") from exc


def _object(segment):
    try:
        value = json.loads(_decode(segment))
    except (ValueError, UnicodeError) as exc:
        raise IdentityRejected("Invalid token JSON") from exc
    if not isinstance(value, dict):
        raise IdentityRejected("Token JSON must be object")
    return value


def _https_issuer(issuer):
    if not isinstance(issuer, str) or len(issuer) > 1024:
        return False
    p = urlsplit(issuer)
    return (p.scheme == "https" and bool(p.hostname) and p.username is None
            and p.password is None and not p.query and not p.fragment)


def _public_key(jwks, kid):
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise IdentityRejected("Untrusted keyset")
    if len(jwks["keys"]) > 50:
        raise IdentityRejected("Too many keys")
    match = [k for k in jwks["keys"] if isinstance(k, dict)
             and k.get("kid") == kid and k.get("kty") == "RSA"
             and k.get("alg") in (None, "RS256") and k.get("use") in (None, "sig")]
    if len(match) != 1:
        raise IdentityRejected("Signing key missing or ambiguous")
    key = match[0]
    try:
        n = _decode(key["n"], 700)
        e = _decode(key["e"], 16)
        if not 256 <= len(n) <= 512 or not 1 <= len(e) <= 4:
            raise IdentityRejected("Invalid RSA key size")
        return rsa.RSAPublicNumbers(int.from_bytes(e, "big"),
                                    int.from_bytes(n, "big")).public_key()
    except (KeyError, TypeError, ValueError) as exc:
        raise IdentityRejected("Invalid public key") from exc


def verify_id_token(token, *, issuer, client_id, expected_nonce, access_token, jwks,
                    now=None):
    """Validate a signed RS256 OIDC ID token bound to this code flow.

    Pins issuer, RP client_id, nonce, access-token hash (at_hash), and times.
    This is an identity assertion only, not permission to consume Privi APIs.
    """
    if rsa is None:
        raise IdentityRejected("Cryptographic dependency missing")
    if not _https_issuer(issuer) or not isinstance(client_id, str) or not client_id:
        raise IdentityRejected("Invalid OIDC verifier configuration")
    if not isinstance(expected_nonce, str) or len(expected_nonce) < 20:
        raise IdentityRejected("Missing original login nonce")
    if not isinstance(access_token, str) or not access_token or len(access_token) > 12288:
        raise IdentityRejected("Missing access token for OIDC binding")
    if not isinstance(token, str) or len(token) > 12288 or token.count(".") != 2:
        raise IdentityRejected("Invalid ID token")
    p0, p1, p2 = token.split(".")
    header = _object(p0)
    claims = _object(p1)
    if (header.get("alg") != "RS256" or header.get("typ") not in (None, "JWT")
            or not isinstance(header.get("kid"), str)):
        raise IdentityRejected("Invalid ID token header")
    pub = _public_key(jwks, header["kid"])
    try:
        pub.verify(_decode(p2, 1000), (p0 + "." + p1).encode("ascii"),
                   padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise IdentityRejected("ID-token signature mismatch") from exc
    if claims.get("iss") != issuer:
        raise IdentityRejected("Issuer mismatch")
    aud = claims.get("aud")
    if isinstance(aud, str):
        audiences = [aud]
    elif isinstance(aud, list) and aud and all(isinstance(a, str) for a in aud):
        audiences = aud
    else:
        raise IdentityRejected("Invalid OIDC audience")
    if client_id not in audiences:
        raise IdentityRejected("Client audience mismatch")
    if len(audiences) > 1 and claims.get("azp") != client_id:
        raise IdentityRejected("Missing authorized party")
    if claims.get("azp") is not None and claims.get("azp") != client_id:
        raise IdentityRejected("Authorized party mismatch")
    timestamp = int(time.time()) if now is None else now
    if type(timestamp) is not int:
        raise IdentityRejected("Invalid time")
    if (type(claims.get("exp")) is not int or claims["exp"] <= timestamp
            or type(claims.get("iat")) is not int
            or claims["iat"] > timestamp + 45):
        raise IdentityRejected("Expired or future ID token")
    if (claims.get("nbf") is not None
            and (type(claims["nbf"]) is not int or claims["nbf"] > timestamp + 45)):
        raise IdentityRejected("ID token not yet valid")
    if (not isinstance(claims.get("sub"), str) or not claims["sub"]
            or len(claims["sub"]) > 256):
        raise IdentityRejected("Missing subject")
    if claims.get("nonce") != expected_nonce:
        raise IdentityRejected("Login nonce mismatch")
    at_hash = base64.urlsafe_b64encode(
        hashlib.sha256(access_token.encode("ascii")).digest()[:16]
    ).rstrip(b"=").decode("ascii")
    if claims.get("at_hash") != at_hash:
        raise IdentityRejected("Access token hash mismatch")
    return {"sub": claims["sub"], "issuer": issuer,
            "oidc_identity_verified": True, "api_access": "NOT_GRANTED",
            "pro_entitlement": "NOT_GRANTED"}
