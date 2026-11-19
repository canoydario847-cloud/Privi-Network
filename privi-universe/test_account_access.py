"""Offline OAuth access and independent Privi Pro entitlement verification tests."""
import base64
import importlib.util
import json
from pathlib import Path
import time
import unittest

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa,padding

p=Path(__file__).with_name("account_access.py")
sp=importlib.util.spec_from_file_location("universe_auth_tests",p)
auth=importlib.util.module_from_spec(sp)
sp.loader.exec_module(auth)

def enc(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

def tok(private,claims,kid="test-key"):
    h={"alg":"RS256","typ":"at+jwt","kid":kid}
    compact=enc(json.dumps(h,separators=(",",":")).encode())+"."+enc(json.dumps(claims,separators=(",",":")).encode())
    sig=private.sign(compact.encode(),padding.PKCS1v15(),hashes.SHA256())
    return compact+"."+enc(sig)

def public_jwks(private,kid="test-key"):
    pn=private.public_key().public_numbers()
    return {"keys":[{"kty":"RSA","kid":kid,"alg":"RS256","use":"sig",
                     "n":enc(pn.n.to_bytes((pn.n.bit_length()+7)//8,"big")),
                     "e":enc(pn.e.to_bytes((pn.e.bit_length()+7)//8,"big"))}]}

class AccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.billing_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def setUp(self):
        self.now=1800000000
        self.cfg={
          "PRIVI_UNIVERSE_OAUTH_ISSUER":"https://id.example.test/",
          "PRIVI_UNIVERSE_OAUTH_AUDIENCE":"privi-universe",
          "PRIVI_UNIVERSE_OAUTH_JWKS":"https://id.example.test/jwks",
          "PRIVI_UNIVERSE_BILLING_ISSUER":"https://billing.example.test/",
          "PRIVI_UNIVERSE_BILLING_AUDIENCE":"privi-pro-entitlement",
          "PRIVI_UNIVERSE_BILLING_JWKS":"https://billing.example.test/jwks",
        }
        self.keys={"https://id.example.test/jwks":public_jwks(self.auth_key),
                   "https://billing.example.test/jwks":public_jwks(self.billing_key)}
        self.load=lambda url:self.keys[url]
        self.claims={"iss":self.cfg["PRIVI_UNIVERSE_OAUTH_ISSUER"],
                     "aud":"privi-universe","sub":"user-001",
                     "iat":self.now-20,"exp":self.now+300,"scope":"privi:account"}
        self.pay={"iss":self.cfg["PRIVI_UNIVERSE_BILLING_ISSUER"],
                  "aud":"privi-pro-entitlement","sub":"user-001",
                  "iat":self.now-20,"exp":self.now+300,"payment_status":"paid",
                  "entitlement":"privi_pro_all","revoked":False}

    def account(self,claims=None,key=None):
        return auth.verify_account_token(tok(key or self.auth_key,claims or self.claims),
                                         self.cfg,loader=self.load,now=self.now)

    def test_valid_account_and_separate_paid_proof(self):
        account=self.account()
        self.assertEqual(account["sub"],"user-001")
        claim=auth.verify_pro_entitlement(
            account,tok(self.billing_key,self.pay),self.cfg,loader=self.load,now=self.now)
        self.assertEqual(claim["tier"],"privi_pro")
        self.assertTrue(claim["verified"])

    def test_no_config_or_bearer_denied(self):
        with self.assertRaises(auth.AccessDenied):
            auth.verify_account_token("bogus",{},loader=self.load,now=self.now)
        with self.assertRaises(auth.AccessDenied):
            auth.bearer("")
        self.assertEqual(auth.bearer("Bearer abc"),"abc")

    def test_bad_account_issuer_audience_expiry_scope(self):
        for key,value in [("iss","https://evil.test/"),("aud","other"),
                          ("exp",self.now),("scope","privi:pro")]:
            claims=dict(self.claims,**{key:value})
            with self.assertRaises(auth.AccessDenied, msg=key):
                self.account(claims)

    def test_forged_or_id_token_denied(self):
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        with self.assertRaises(auth.AccessDenied):
            self.account(key=other)
        token=tok(self.auth_key,self.claims)
        part=token.split(".")
        part[0]=enc(json.dumps({"alg":"none","typ":"at+jwt","kid":"test-key"}).encode())
        with self.assertRaises(auth.AccessDenied):
            auth.verify_account_token(".".join(part),self.cfg,loader=self.load,now=self.now)
        part[0]=enc(json.dumps({"alg":"RS256","typ":"JWT","kid":"test-key"}).encode())
        with self.assertRaises(auth.AccessDenied):
            auth.verify_account_token(".".join(part),self.cfg,loader=self.load,now=self.now)

    def test_payment_proof_cannot_be_self_claimed(self):
        account=self.account(dict(self.claims,entitlement="privi_pro_all"))
        with self.assertRaises(auth.AccessDenied):
            auth.verify_pro_entitlement(account,tok(self.auth_key,self.pay),
                                       self.cfg,loader=self.load,now=self.now)
        for key,value in [("sub","another-user"),("revoked",True),
                          ("payment_status","unpaid"),("entitlement","guest")]:
            pay=dict(self.pay,**{key:value})
            with self.assertRaises(auth.AccessDenied,msg=key):
                auth.verify_pro_entitlement(account,tok(self.billing_key,pay),
                                           self.cfg,loader=self.load,now=self.now)

    def test_missing_proof_configuration_fails_closed(self):
        bad=dict(self.cfg)
        bad.pop("PRIVI_UNIVERSE_BILLING_JWKS")
        with self.assertRaises(auth.AccessDenied):
            auth.verify_pro_entitlement(self.account(),tok(self.billing_key,self.pay),
                                       bad,loader=self.load,now=self.now)

    def test_hardcoded_insecure_keyset_urls_rejected(self):
        cfg=dict(self.cfg,PRIVI_UNIVERSE_OAUTH_JWKS="http://localhost:1234/jwks")
        self.assertFalse(auth.configured(cfg))
        with self.assertRaises(auth.AccessDenied):
            auth.verify_account_token(tok(self.auth_key,self.claims),cfg,
                                      loader=self.load,now=self.now)

if __name__=="__main__":
    unittest.main()
