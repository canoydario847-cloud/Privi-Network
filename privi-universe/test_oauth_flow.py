"""Offline OAuth code-exchange integration tests — no live IdP or user sessions."""
import importlib.util
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("privi_universe_oauth_flow", HERE/"oauth_flow.py")
flow=importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)

CONFIG={
    "issuer":"https://id.example.test/",
    "authorization_endpoint":"https://id.example.test/authorize",
    "token_endpoint":"https://id.example.test/oauth/token",
    "redirect_uri":"https://privi-universe-demo.onrender.com/oauth/callback",
    "client_id":"privi-universe-test",
}

class OAuthFlowTests(unittest.TestCase):
    def setUp(self):
        self.clock=[1000]
        self.store=flow.LoginTransactions(now=lambda:self.clock[0])
        self.auth=flow.authorization_request(CONFIG,self.store)
        self.state=self.auth["state"]
        self.code="synthetic-onetime-code"
        self.called=[]
    def post(self,endpoint,params):
        self.called.append((endpoint,params))
        return {"token_type":"Bearer","access_token":"signed-test-token"}
    def verifier(self, token,config):
        self.assertEqual(token,"signed-test-token")
        return {"sub":"test-subject"}

    def test_pkce_code_exchange_and_no_browser_session(self):
        u=urlsplit(self.auth["url"])
        self.assertEqual(u.scheme,"https")
        self.assertEqual(u.hostname,"id.example.test")
        params=parse_qs(u.query)
        self.assertEqual(params["response_type"],["code"])
        self.assertEqual(params["code_challenge_method"],["S256"])
        self.assertNotIn("code_verifier",params)
        result=flow.finish_code_exchange(CONFIG,self.store,state=self.state,
            code=self.code,auth_config={},token_post=self.post,
            validate_access_token=self.verifier)
        self.assertEqual(result["subject"],"test-subject")
        self.assertEqual(result["browser_session"],"NOT_ISSUED")
        self.assertEqual(result["pro_access"],"NOT_GRANTED")
        self.assertEqual(len(self.called),1)
        self.assertEqual(self.called[0][1]["code"],self.code)
        with self.assertRaises(flow.AccessDenied):
            flow.finish_code_exchange(CONFIG,self.store,state=self.state,
                code=self.code,auth_config={},token_post=self.post,
                validate_access_token=self.verifier)
        self.assertEqual(len(self.called),1)

    def test_wrong_state_and_callback_do_not_contact_idp(self):
        with self.assertRaises(flow.AccessDenied):
            flow.finish_code_exchange(CONFIG,self.store,state="wrong",code=self.code,
                auth_config={},token_post=self.post,validate_access_token=self.verifier)
        self.assertEqual(self.called,[])
        wrong=dict(CONFIG,redirect_uri="https://privi-universe-demo.onrender.com/oauth/callback?attack=1")
        with self.assertRaises(flow.AccessDenied):
            flow.finish_code_exchange(wrong,self.store,state=self.state,code=self.code,
                auth_config={},token_post=self.post,validate_access_token=self.verifier)
        self.assertEqual(self.called,[])

    def test_invalid_code_rejected(self):
        for code in ("","a\nb","x"*3000,None):
            with self.assertRaises(flow.AccessDenied):
                flow.finish_code_exchange(CONFIG,self.store,state=self.state,code=code,
                    auth_config={},token_post=self.post,validate_access_token=self.verifier)
        self.assertEqual(self.called,[])

    def test_invalid_token_response_rejected(self):
        for payload in ({"access_token":"t","token_type":"mac"},
                        {"token_type":"Bearer","id_token":"not-an-access-token"},
                        {"access_token":"t"*13000,"token_type":"Bearer"}):
            store=flow.LoginTransactions()
            state=flow.authorization_request(CONFIG,store)["state"]
            with self.assertRaises(flow.AccessDenied):
                flow.finish_code_exchange(CONFIG,store,state=state,code=self.code,
                    auth_config={},token_post=lambda u,b:payload,
                    validate_access_token=self.verifier)

    def test_forged_access_token_rejected(self):
        def fail(token,settings):
            raise flow.AccessDenied("signature mismatch")
        with self.assertRaises(flow.AccessDenied):
            flow.finish_code_exchange(CONFIG,self.store,state=self.state,code=self.code,
                auth_config={},token_post=self.post,validate_access_token=fail)

    def test_endpoint_mismatch_rejected(self):
        for field,val in (("issuer","http://id.example.test"),
                          ("token_endpoint","https://evil.example/token"),
                          ("authorization_endpoint","https://evil.example/authorize"),
                          ("redirect_uri","https://attacker.example/oauth/callback?x=1"),
                          ("client_id","")):
            with self.assertRaises(flow.AccessDenied):
                flow.validate_flow_config(dict(CONFIG,**{field:val}))

if __name__=="__main__":
    unittest.main()
