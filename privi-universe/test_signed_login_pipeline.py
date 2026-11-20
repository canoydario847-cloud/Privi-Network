"""Cryptographically signed end-to-end Privi Universe login-pipeline tests.

No live IdP, requests, accounts, billing or login routes. Uses throwaway RSA
keys to sign BOTH a real OAuth access JWT and a distinct OIDC ID token, then
runs production verifiers and the actual opaque SessionStore together.
"""
import base64
import hashlib
import json
import time
import unittest
from urllib.parse import urlsplit, parse_qs

try:
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import hashes
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

from login_protocol import LoginTransactions
from oauth_flow import authorization_request
from account_access import AccessDenied, verify_account_token
from oidc_identity import IdentityRejected
from browser_sessions import SessionStore, SessionDenied
from login_pipeline import complete_verified_login

ISSUER = "https://id.example.test/"
CLIENT_ID = "privi-universe"
JWKS_URL = "https://id.example.test/jwks"
CONFIG = {
    "issuer": ISSUER,
    "authorization_endpoint": "https://id.example.test/authorize",
    "token_endpoint": "https://id.example.test/token",
    "redirect_uri": "https://privi-universe-demo.onrender.com/oauth/callback",
    "client_id": CLIENT_ID,
}
AUTH_CONFIG = {
    "PRIVI_UNIVERSE_OAUTH_ISSUER": ISSUER,
    "PRIVI_UNIVERSE_OAUTH_AUDIENCE": "privi-universe-api",
    "PRIVI_UNIVERSE_OAUTH_JWKS": JWKS_URL,
}


def enc(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def jwk(key, kid):
    n = key.public_key().public_numbers()
    return {"kty": "RSA", "kid": kid, "alg": "RS256", "use": "sig",
            "n": enc(n.n.to_bytes((n.n.bit_length()+7)//8, "big")),
            "e": enc(n.e.to_bytes((n.e.bit_length()+7)//8, "big"))}


def signed_jwt(key, kid, typ, claims):
    h = enc(json.dumps({"alg": "RS256", "typ": typ, "kid": kid}).encode())
    b = enc(json.dumps(claims).encode())
    message = h + "." + b
    return message + "." + enc(key.sign(message.encode("ascii"), padding.PKCS1v15(), hashes.SHA256()))


@unittest.skipUnless(HAS_CRYPTO, "cryptography dependency required for signing suite")
class SignedLoginIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.id_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.now = int(time.time())
        self.transactions = LoginTransactions(now=lambda: self.now)
        self.sessions = SessionStore(now=lambda: self.now)
        request = authorization_request(CONFIG, self.transactions)
        self.state = request["state"]
        self.nonce = parse_qs(urlsplit(request["url"]).query)["nonce"][0]
        self.jwks = {"keys": [jwk(self.auth_key, "access-key"), jwk(self.id_key, "id-key")]}
        self.subject = "alice"
        self.access_claims = {
            "iss": ISSUER, "aud": AUTH_CONFIG["PRIVI_UNIVERSE_OAUTH_AUDIENCE"],
            "sub": self.subject, "iat": self.now-10, "exp": self.now+240,
            "scope": "privi:account",
        }
        self.access_token = signed_jwt(self.auth_key, "access-key", "at+jwt", self.access_claims)
        self.id_claims = {
            "iss": ISSUER, "aud": CLIENT_ID, "sub": self.subject,
            "iat": self.now-10, "exp": self.now+240, "nonce": self.nonce,
            "at_hash": enc(hashlib.sha256(self.access_token.encode("ascii")).digest()[:16]),
        }
        self.id_token = signed_jwt(self.id_key, "id-key", "JWT", self.id_claims)

    def run_login(self, *, access_token=None, id_token=None, jwks=None):
        access_token = self.access_token if access_token is None else access_token
        id_token = self.id_token if id_token is None else id_token
        keys = self.jwks if jwks is None else jwks
        def real_access(token, settings):
            return verify_account_token(token, settings, loader=lambda url: keys, now=self.now)
        return complete_verified_login(
            CONFIG, self.transactions, self.sessions, state=self.state,
            code="one-time-code", oauth_config=AUTH_CONFIG, id_token_jwks_uri=JWKS_URL,
            post_token=lambda url, body: {
                "token_type": "Bearer", "access_token": access_token, "id_token": id_token
            },
            get_jwks=lambda url: keys,
            verify_access=real_access, now=self.now,
        )

    def test_valid_real_signatures_issue_account_only_session(self):
        result = self.run_login()
        self.assertTrue(result["account_verified"])
        self.assertEqual(result["subject"], self.subject)
        self.assertEqual(result["pro_access"], "NOT_GRANTED")
        self.assertEqual(result["id_token"], "NOT_RETURNED")
        handle = result["session"]["session_handle"]
        self.assertEqual(self.sessions.validate(handle)["subject"], self.subject)
        self.assertFalse(self.sessions.validate(handle)["pro_access"])
        self.assertIn("HttpOnly", result["session"]["cookie"])
        with self.assertRaises(AccessDenied):
            self.run_login()

    def test_forged_access_token_cannot_issue_session(self):
        forged = signed_jwt(self.attacker_key, "access-key", "at+jwt", self.access_claims)
        with self.assertRaises(AccessDenied):
            self.run_login(access_token=forged)
        self.assertEqual(len(self.sessions._items), 0)

    def test_forged_id_token_cannot_issue_session(self):
        forged = signed_jwt(self.attacker_key, "id-key", "JWT", self.id_claims)
        with self.assertRaises(IdentityRejected):
            self.run_login(id_token=forged)
        self.assertEqual(len(self.sessions._items), 0)

    def test_changed_nonce_or_access_token_binding_denied(self):
        for invalid in [
            dict(self.id_claims, nonce="attacker-nonce"),
            dict(self.id_claims, at_hash="invalid-hash")
        ]:
            self.setUp()
            with self.assertRaises(IdentityRejected):
                self.run_login(id_token=signed_jwt(self.id_key, "id-key", "JWT", invalid))
            self.assertEqual(len(self.sessions._items), 0)

    def test_correctly_signed_mismatched_subject_denied(self):
        invalid = dict(self.id_claims, sub="bob")
        with self.assertRaises(AccessDenied):
            self.run_login(id_token=signed_jwt(self.id_key, "id-key", "JWT", invalid))
        self.assertEqual(len(self.sessions._items), 0)

    def test_expired_access_or_id_token_denied(self):
        expired_access = signed_jwt(
            self.auth_key, "access-key", "at+jwt",
            dict(self.access_claims, exp=self.now-1))
        with self.assertRaises(AccessDenied):
            self.run_login(access_token=expired_access)
        self.setUp()
        expired_id = signed_jwt(
            self.id_key, "id-key", "JWT", dict(self.id_claims, exp=self.now-1))
        with self.assertRaises(IdentityRejected):
            self.run_login(id_token=expired_id)
        self.assertEqual(len(self.sessions._items), 0)

    def test_malformed_key_source_denied(self):
        with self.assertRaises(AccessDenied):
            self.run_login(jwks={"keys":[]})
        self.assertEqual(len(self.sessions._items), 0)


if __name__ == "__main__":
    unittest.main()
