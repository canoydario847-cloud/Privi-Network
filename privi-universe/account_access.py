"""Privi Universe read-only OAuth resource-server and entitlement gate.

Auth is disabled (fail closed) until trusted IdP and billing JWT settings are
configured. This module does NOT implement browser login, account creation,
payment processing or real Privi Pro access. JWTs must be signed RS256 access
tokens from independent verified issuers and audiences. Never trust client
supplied 'pro' claims without separately verified billing issuer proof.
"""
from __future__ import annotations

import base64
import json
import os
import re
import ssl
import time
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.parse import urlsplit

try:
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidSignature
except ImportError:
    padding = rsa = hashes = InvalidSignature = None

MAX_JWT=12288
MAX_JWKS=65536
MAX_CLOCK_SKEW=45
JWT_PART=re.compile(r"^[A-Za-z0-9_-]+$")


class AccessDenied(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AccessDenied("Identity keys redirect refused")


def _b64(value, limit=MAX_JWT):
    if not isinstance(value,str) or not value or len(value)>limit or not JWT_PART.fullmatch(value):
        raise AccessDenied("Malformed encoded token")
    try:
        return base64.urlsafe_b64decode(value+"="*(-len(value)%4))
    except (ValueError,TypeError) as exc:
        raise AccessDenied("Malformed token encoding") from exc


def _json(value):
    try:
        data=json.loads(_b64(value))
        if not isinstance(data,dict):
            raise AccessDenied("JWT part must be object")
        return data
    except (UnicodeError,ValueError) as exc:
        raise AccessDenied("Invalid JWT JSON") from exc


def _https(url):
    p=urlsplit(url)
    return p.scheme=="https" and bool(p.hostname) and not p.username and not p.password and not p.fragment and not p.query


def config_from_env():
    """No issuer or secret defaults; never enable auth accidentally."""
    keys=("PRIVI_UNIVERSE_OAUTH_ISSUER","PRIVI_UNIVERSE_OAUTH_AUDIENCE",
          "PRIVI_UNIVERSE_OAUTH_JWKS",
          "PRIVI_UNIVERSE_BILLING_ISSUER","PRIVI_UNIVERSE_BILLING_AUDIENCE",
          "PRIVI_UNIVERSE_BILLING_JWKS")
    vals={k:os.environ.get(k,"").strip() for k in keys}
    return vals


def configured(cfg):
    fields=("PRIVI_UNIVERSE_OAUTH_ISSUER","PRIVI_UNIVERSE_OAUTH_AUDIENCE",
            "PRIVI_UNIVERSE_OAUTH_JWKS")
    return (all(cfg.get(k) for k in fields) and
            _https(cfg[fields[0]]) and _https(cfg[fields[2]]))


def billing_configured(cfg):
    fields=("PRIVI_UNIVERSE_BILLING_ISSUER","PRIVI_UNIVERSE_BILLING_AUDIENCE",
            "PRIVI_UNIVERSE_BILLING_JWKS")
    return (all(cfg.get(k) for k in fields) and
            _https(cfg[fields[0]]) and _https(cfg[fields[2]]) and configured(cfg))


def fetch_keys(url):
    if not _https(url):
        raise AccessDenied("JWKS must be HTTPS")
    opener=build_opener(HTTPSHandler(context=ssl.create_default_context()),NoRedirect())
    req=Request(url,headers={"Accept":"application/json","User-Agent":"PriviUniverseResourceServer/1"},method="GET")
    try:
        with opener.open(req,timeout=5) as resp:
            if resp.status!=200:
                raise AccessDenied("JWKS HTTP status invalid")
            raw=resp.read(MAX_JWKS+1)
    except (OSError,TimeoutError,ValueError) as exc:
        raise AccessDenied("JWKS unavailable") from exc
    if len(raw)>MAX_JWKS:
        raise AccessDenied("JWKS too large")
    try:
        obj=json.loads(raw)
    except (UnicodeError,ValueError) as exc:
        raise AccessDenied("JWKS malformed") from exc
    if not isinstance(obj,dict) or not isinstance(obj.get("keys"),list) or len(obj["keys"])>50:
        raise AccessDenied("JWKS malformed")
    return obj


def verify_jwt(token, *, issuer,audience,jwks, required_scope=None,now=None):
    """Verify RS256 JWT access tokens (not ID tokens), issuer, audience, time.

    jwks is supplied by a trusted JWKS fetch, NOT user input. Public modulus
    and exponent are bounded to mitigate malicious-key resource exhaustion.
    """
    if rsa is None:
        raise AccessDenied("JWT signature dependency unavailable")
    if not _https(issuer) or not isinstance(audience,str) or not audience:
        raise AccessDenied("Invalid verifier configuration")
    if not isinstance(token,str) or len(token)>MAX_JWT or token.count(".")!=2:
        raise AccessDenied("Invalid access token")
    header_segment,claims_segment,signature_segment=token.split(".")
    header=_json(header_segment)
    claims=_json(claims_segment)
    if header.get("alg")!="RS256" or header.get("typ") not in ("at+jwt","application/at+jwt"):
        raise AccessDenied("Access-token type or algorithm invalid")
    kid=header.get("kid")
    if not isinstance(kid,str) or not 1<=len(kid)<=128:
        raise AccessDenied("Missing signing key ID")
    if not isinstance(jwks,dict) or not isinstance(jwks.get("keys"),list):
        raise AccessDenied("Invalid trusted keyset")
    matches=[k for k in jwks["keys"] if isinstance(k,dict) and
             k.get("kid")==kid and k.get("kty")=="RSA" and
             k.get("alg") in (None,"RS256") and k.get("use") in (None,"sig")]
    if len(matches)!=1:
        raise AccessDenied("Unknown or ambiguous signing key")
    key=matches[0]
    try:
        n_bytes=_b64(key["n"],700)
        e_bytes=_b64(key["e"],16)
        if not 256<=len(n_bytes)<=512 or not 1<=len(e_bytes)<=4:
            raise AccessDenied("RSA public key size invalid")
        public=rsa.RSAPublicNumbers(
            int.from_bytes(e_bytes,"big"),int.from_bytes(n_bytes,"big")).public_key()
        public.verify(_b64(signature_segment,1000),(header_segment+"."+claims_segment).encode("ascii"),
                      padding.PKCS1v15(),hashes.SHA256())
    except (ValueError,TypeError,KeyError,InvalidSignature) as exc:
        raise AccessDenied("Invalid JWT signature") from exc
    now=int(time.time()) if now is None else now
    aud=claims.get("aud")
    valid_aud=audience in aud if isinstance(aud,list) else aud==audience
    if claims.get("iss")!=issuer or not valid_aud:
        raise AccessDenied("Issuer or audience mismatch")
    if type(claims.get("exp")) is not int or claims["exp"]<=now:
        raise AccessDenied("Expired access token")
    if type(claims.get("iat")) is not int or claims["iat"]>now+MAX_CLOCK_SKEW:
        raise AccessDenied("Invalid issuance time")
    if claims.get("nbf") is not None and (
            type(claims["nbf"]) is not int or claims["nbf"]>now+MAX_CLOCK_SKEW):
        raise AccessDenied("Token not yet valid")
    if not isinstance(claims.get("sub"),str) or not claims["sub"] or len(claims["sub"])>256:
        raise AccessDenied("Missing subject")
    scopes=claims.get("scope","")
    if not isinstance(scopes,str) or len(scopes)>2048:
        raise AccessDenied("Invalid scopes")
    if required_scope and required_scope not in scopes.split():
        raise AccessDenied("Insufficient scope")
    return claims


def bearer(header):
    if not isinstance(header,str) or not header.startswith("Bearer "):
        raise AccessDenied("Bearer token required")
    return header[7:]


def verify_account_token(token,config,*,loader=fetch_keys,now=None):
    if not configured(config):
        raise AccessDenied("Identity provider is not configured")
    keyset=loader(config["PRIVI_UNIVERSE_OAUTH_JWKS"])
    return verify_jwt(token,issuer=config["PRIVI_UNIVERSE_OAUTH_ISSUER"],
                      audience=config["PRIVI_UNIVERSE_OAUTH_AUDIENCE"],
                      jwks=keyset,required_scope="privi:account",now=now)


def verify_pro_entitlement(account,proof,config,*,loader=fetch_keys,now=None):
    """Additional *separate* signed billing proof, bound to authenticated user.

    Requires confirmed payment status AND explicit all-products entitlement.
    A regular OAuth token containing 'pro' is never enough.
    """
    if not billing_configured(config):
        raise AccessDenied("Trusted billing entitlement issuer not configured")
    claims=verify_jwt(proof,issuer=config["PRIVI_UNIVERSE_BILLING_ISSUER"],
                      audience=config["PRIVI_UNIVERSE_BILLING_AUDIENCE"],
                      jwks=loader(config["PRIVI_UNIVERSE_BILLING_JWKS"]),now=now)
    if claims.get("sub")!=account.get("sub"):
        raise AccessDenied("Billing subject mismatch")
    if (claims.get("payment_status")!="paid" or claims.get("entitlement")!="privi_pro_all"
            or claims.get("revoked") is not False):
        raise AccessDenied("Entitlement unverified, revoked or unpaid")
    return {"tier":"privi_pro","subject":account["sub"],"verified":True}
