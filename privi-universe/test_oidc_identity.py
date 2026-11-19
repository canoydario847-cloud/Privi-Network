"""OIDC RP ID token validation: signature, nonce, at_hash and audience.

Offline fixtures only; cryptography tests skip in Render stdlib build and run
in separately pinned signing GitHub Actions workflow.
"""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    CRYPTO=True
except ImportError:
    CRYPTO=False

spec=importlib.util.spec_from_file_location("universe_oidc_identity",
                                             Path(__file__).with_name("oidc_identity.py"))
oidc=importlib.util.module_from_spec(spec)
spec.loader.exec_module(oidc)

def enc(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@unittest.skipUnless(CRYPTO, "cryptography required for signature tests")
class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.alien=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def setUp(self):
        self.now=1800000000
        self.issuer="https://id.example.test/"
        self.client="privi-universe"
        self.nonce="original-login-nonce-012345678901234"
        self.access="synthetic-access-token"
        self.claims={"iss":self.issuer,"aud":self.client,"sub":"user-001",
                     "iat":self.now-40,"exp":self.now+200,"nonce":self.nonce,
                     "at_hash":enc(hashlib.sha256(self.access.encode()).digest()[:16])}
        self.jwks=self.keys(self.key)
    @staticmethod
    def keys(private):
        num=private.public_key().public_numbers()
        return {"keys":[{"kty":"RSA","kid":"key1","alg":"RS256","use":"sig",
                         "n":enc(num.n.to_bytes((num.n.bit_length()+7)//8,"big")),
                         "e":enc(num.e.to_bytes((num.e.bit_length()+7)//8,"big"))}]}
    def token(self,claims=None,key=None):
        head=enc(json.dumps({"alg":"RS256","typ":"JWT","kid":"key1"}).encode())
        body=enc(json.dumps(self.claims if claims is None else claims).encode())
        msg=head+"."+body
        sig=(key or self.key).sign(msg.encode(),padding.PKCS1v15(),hashes.SHA256())
        return msg+"."+enc(sig)
    def verify(self,token=None,**kw):
        args={"issuer":self.issuer,"client_id":self.client,
              "expected_nonce":self.nonce,"access_token":self.access,
              "jwks":self.jwks,"now":self.now}
        args.update(kw)
        return oidc.verify_id_token(token if token is not None else self.token(),**args)
    def test_valid_identity_does_not_grant_pro(self):
        result=self.verify()
        self.assertEqual(result["sub"],"user-001")
        self.assertEqual(result["api_access"],"NOT_GRANTED")
        self.assertEqual(result["pro_entitlement"],"NOT_GRANTED")
    def test_reject_wrong_identity_or_binding(self):
        for key,value in [
            ("iss","https://evil.example/"),("aud","another-client"),
            ("nonce","attacker-nonce"),("at_hash","wrong"),
            ("exp",self.now),("iat",self.now+1000),("sub",""),
            ("azp","other-client"),
        ]:
            with self.subTest(key=key),self.assertRaises(oidc.IdentityRejected):
                self.verify(self.token(dict(self.claims,**{key:value})))
    def test_multi_audience_requires_azp(self):
        claims=dict(self.claims,aud=[self.client,"secondary"])
        with self.assertRaises(oidc.IdentityRejected):
            self.verify(self.token(claims))
        claims["azp"]=self.client
        self.assertTrue(self.verify(self.token(claims))["oidc_identity_verified"])
    def test_forgery_and_wrong_access_token_rejected(self):
        with self.assertRaises(oidc.IdentityRejected):
            self.verify(self.token(key=self.alien))
        with self.assertRaises(oidc.IdentityRejected):
            self.verify(access_token="other-access-token")
        with self.assertRaises(oidc.IdentityRejected):
            self.verify(expected_nonce="other-login-nonce")
    def test_untrusted_key_id_or_alg_rejected(self):
        with self.assertRaises(oidc.IdentityRejected):
            self.verify(jwks={"keys":[]})
        parts=self.token().split(".")
        parts[0]=enc(json.dumps({"alg":"none","typ":"JWT","kid":"key1"}).encode())
        with self.assertRaises(oidc.IdentityRejected):
            self.verify(".".join(parts))
    def test_missing_crypto_fails_closed(self):
        old=oidc.rsa
        try:
            oidc.rsa=None
            with self.assertRaises(oidc.IdentityRejected):
                self.verify()
        finally:
            oidc.rsa=old


if __name__=="__main__":
    unittest.main()
