"""OIDC preflight tests. No network, real account, or payment calls."""
import importlib.util
from pathlib import Path
import unittest

here=Path(__file__).resolve().parent
def module(filename):
    spec=importlib.util.spec_from_file_location(filename,here/(filename+".py"))
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

pre=module("oidc_preflight")
login=module("login_protocol")
ISSUER="https://id.example.test/tenant"
AUTH="https://id.example.test/oauth2/authorize"
TOKEN="https://id.example.test/oauth2/token"
JWKS="https://id.example.test/.well-known/jwks.json"
REDIRECT="https://privi-universe-demo.onrender.com/oauth/callback"
CLIENT="privi-universe-demo"

def metadata():
    return {"issuer":ISSUER,"authorization_endpoint":AUTH,
            "token_endpoint":TOKEN,"jwks_uri":JWKS,
            "response_types_supported":["code"],
            "grant_types_supported":["authorization_code"],
            "code_challenge_methods_supported":["S256"],
            "id_token_signing_alg_values_supported":["RS256"]}

def validate(m):
    return pre.validate_metadata(m,issuer=ISSUER,client_id=CLIENT,
                                 redirect_uri=REDIRECT,jwks_uri=JWKS,
                                 expected_authorize=AUTH,expected_token=TOKEN)

class OidcPreflightTests(unittest.TestCase):
    def test_valid_pinned_provider_metadata(self):
        result=validate(metadata())
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"],"METADATA_VALIDATED_NOT_LOGIN_ENABLED")
        self.assertEqual(result["code_challenge_method"],"S256")

    def test_reject_issuer_and_endpoints(self):
        for field,value in (
            ("issuer","https://evil.example/"),
            ("authorization_endpoint","https://evil.example/auth"),
            ("token_endpoint","https://evil.example/token"),
            ("jwks_uri","https://evil.example/keys")):
            m=metadata()
            m[field]=value
            with self.assertRaises(pre.PreflightError,msg=field):
                validate(m)

    def test_require_pkce_and_auth_code_support(self):
        for field in ("response_types_supported","grant_types_supported",
                      "code_challenge_methods_supported","id_token_signing_alg_values_supported"):
            m=metadata()
            m[field]=[]
            with self.assertRaises(pre.PreflightError,msg=field):
                validate(m)

    def test_reject_insecure_https_and_credentials(self):
        for uri in ("http://id.example.test/","https://user@id.example.test/",
                    "https://localhost/","https://id.example.test/#fragment",
                    "https://id.example.test/?evil=1",
                    "https://id.example.test:badport/"):
            self.assertFalse(pre.secure_url(uri),msg=uri)
        self.assertTrue(pre.secure_url(ISSUER))

    def test_authorization_parameters_never_expose_secret(self):
        tx=login.LoginTransactions(now=lambda:123).issue(issuer=ISSUER,redirect_uri=REDIRECT)
        args=pre.authorization_parameters(transaction=tx,client_id=CLIENT,redirect_uri=REDIRECT)
        self.assertEqual(args["code_challenge_method"],"S256")
        self.assertEqual(args["response_type"],"code")
        self.assertEqual(args["scope"],"openid")
        self.assertNotIn("code_verifier",args)
        self.assertNotIn("token",args)
        self.assertNotIn("client_secret",args)

    def test_non_s256_or_invalid_client_rejected(self):
        tx=login.LoginTransactions(now=lambda:123).issue(issuer=ISSUER,redirect_uri=REDIRECT)
        tx["code_challenge_method"]="plain"
        with self.assertRaises(pre.PreflightError):
            pre.authorization_parameters(transaction=tx,client_id=CLIENT,redirect_uri=REDIRECT)
        with self.assertRaises(pre.PreflightError):
            pre.validate_metadata(metadata(),issuer=ISSUER,client_id="",redirect_uri=REDIRECT,jwks_uri=JWKS)

if __name__=="__main__":
    unittest.main()
