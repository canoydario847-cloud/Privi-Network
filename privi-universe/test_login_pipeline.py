"""Privi Universe end-to-end login pipeline with mocked IdP; no live login."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("privi_universe_login_pipeline",ROOT/"login_pipeline.py")
pipeline=importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

FLOW={
    "issuer":"https://id.example.test/",
    "authorization_endpoint":"https://id.example.test/authorize",
    "token_endpoint":"https://id.example.test/token",
    "redirect_uri":"https://privi-universe-demo.onrender.com/oauth/callback",
    "client_id":"privi-universe",
}
AUTH={"PRIVI_UNIVERSE_OAUTH_ISSUER":FLOW["issuer"],
      "PRIVI_UNIVERSE_OAUTH_AUDIENCE":"privi-api",
      "PRIVI_UNIVERSE_OAUTH_JWKS":"https://id.example.test/jwks"}

class FakeState:
    def __init__(self):
        self.used=False
    def consume(self,state,*,issuer,redirect_uri):
        if self.used or state!="good-state" or issuer!=FLOW["issuer"] or redirect_uri!=FLOW["redirect_uri"]:
            raise ValueError("invalid or replayed state")
        self.used=True
        return {"code_verifier":"v"*64,"nonce":"expected-auth-nonce-1234567890"}

class FakeSession:
    def __init__(self):
        self.calls=[]
    def issue(self,**kwargs):
        self.calls.append(kwargs)
        return {"cookie":"test-cookie","access":"ACCOUNT_ONLY_NO_PRO"}

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.state=FakeState()
        self.sessions=FakeSession()
        self.calls=[]
        self.reply={"token_type":"Bearer","access_token":"signed-access",
                    "id_token":"signed-id"}
    def post(self,url,body):
        self.calls.append(("post",url,body))
        return self.reply
    def jwks(self,url):
        self.calls.append(("jwks",url))
        return {"keys":["from-configured-idp"]}
    def access(self,token,config):
        self.calls.append(("access",token))
        return {"sub":"alice"}
    def identity(self,token,**kw):
        self.calls.append(("identity",kw["expected_nonce"],kw["access_token"],kw["client_id"]))
        return {"oidc_identity_verified":True,"sub":"alice","issuer":FLOW["issuer"]}
    def complete(self,**overrides):
        args=dict(config=FLOW,transaction_store=self.state,session_store=self.sessions,
                  state="good-state",code="one-time-code",oauth_config=AUTH,
                  id_token_jwks_uri=AUTH["PRIVI_UNIVERSE_OAUTH_JWKS"],
                  post_token=self.post,get_jwks=self.jwks,
                  verify_access=self.access,verify_identity=self.identity,now=1000)
        args.update(overrides)
        return pipeline.complete_verified_login(**args)

    def test_valid_chain_issues_session_last(self):
        result=self.complete()
        self.assertTrue(result["account_verified"])
        self.assertEqual(result["pro_access"],"NOT_GRANTED")
        self.assertEqual(result["access_token"],"NOT_RETURNED")
        self.assertEqual(len(self.sessions.calls),1)
        self.assertEqual(self.sessions.calls[0]["subject"],"alice")
        self.assertEqual(self.calls[-1][0],"identity")
        self.assertEqual(self.calls[-1][1],"expected-auth-nonce-1234567890")
        self.assertEqual(self.calls[-1][2],"signed-access")
        with self.assertRaises(pipeline.AccessDenied):
            self.complete()
        self.assertEqual(len(self.sessions.calls),1)

    def test_wrong_issuer_rejected_before_state_use(self):
        with self.assertRaises(pipeline.AccessDenied):
            self.complete(oauth_config=dict(AUTH,PRIVI_UNIVERSE_OAUTH_ISSUER="https://evil.example/"))
        self.assertFalse(self.state.used)
        self.assertEqual(self.sessions.calls,[])

    def test_unpinned_jwks_denied_without_exchange(self):
        with self.assertRaises(pipeline.AccessDenied):
            self.complete(id_token_jwks_uri="https://evil.example/jwks")
        self.assertFalse(self.state.used)
        self.assertEqual(self.calls,[])

    def test_token_replies_missing_or_wrong_type_denied(self):
        for response in ({"token_type":"Bearer","access_token":"signed-access"},
                         {"token_type":"mac","id_token":"signed-id","access_token":"signed-access"}):
            self.setUp()
            self.reply=response
            with self.assertRaises(pipeline.AccessDenied):
                self.complete()
            self.assertTrue(self.state.used)
            self.assertEqual(self.sessions.calls,[])

    def test_identity_subject_mismatch_and_missing_verification_denied(self):
        for claims in ({"oidc_identity_verified":True,"sub":"bob","issuer":FLOW["issuer"]},
                       {"oidc_identity_verified":False,"sub":"alice","issuer":FLOW["issuer"]},
                       {"oidc_identity_verified":True,"sub":"alice","issuer":"https://other.example/"}):
            self.setUp()
            with self.assertRaises(pipeline.AccessDenied):
                self.complete(verify_identity=lambda tok,**kw:claims)
            self.assertEqual(self.sessions.calls,[])

    def test_forged_access_and_nonce_fail_before_session(self):
        def fail(token,cfg):
            raise pipeline.AccessDenied("untrusted JWT")
        with self.assertRaises(pipeline.AccessDenied):
            self.complete(verify_access=fail)
        self.assertEqual(self.sessions.calls,[])

    def test_invalid_state_and_code_fail_without_network(self):
        with self.assertRaises(pipeline.AccessDenied):
            self.complete(state="fake")
        self.assertEqual(self.calls,[])
        self.assertEqual(self.sessions.calls,[])
        with self.assertRaises(pipeline.AccessDenied):
            self.complete(code="bad\ncode")
        self.assertEqual(self.calls,[])

    def test_session_failure_never_grants_access(self):
        def fail_issue(**kwargs):
            raise RuntimeError("store unavailable")
        self.sessions.issue=fail_issue
        with self.assertRaises(RuntimeError):
            self.complete()
        with self.assertRaises(pipeline.AccessDenied):
            self.complete()

if __name__=="__main__":
    unittest.main()
