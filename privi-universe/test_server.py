"""Privi Universe portal regression and honest availability tests."""
import http.client
import importlib.util
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

spec=importlib.util.spec_from_file_location("privi_universe_portal",Path(__file__).with_name("server.py"))
app=importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
        cls.port=cls.httpd.server_address[1]
        cls.thread=threading.Thread(target=cls.httpd.serve_forever,daemon=True)
        cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)
    def call(self,method,path):
        conn=http.client.HTTPConnection("127.0.0.1",self.port,timeout=3)
        try:
            conn.request(method,path)
            res=conn.getresponse()
            return res.status,dict(res.getheaders()),res.read()
        finally:
            conn.close()
    def test_home_and_health(self):
        status,headers,body=self.call("GET","/")
        self.assertEqual(status,200)
        self.assertIn(b"PRELAUNCH",body)
        self.assertIn(b"Mission",body)
        self.assertIn(b"Made by Dario Canoy",body)
        self.assertIn(b"Privi Universe",body)
        self.assertEqual(headers["Cache-Control"],"no-store")
        self.assertIn("default-src 'none'",headers["Content-Security-Policy"])
        status,_,body=self.call("GET","/health")
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)["mode"],"PRELAUNCH_PORTAL")
    def test_present_oauth_settings_are_not_called_verified(self):
        original=app.account_access.config_from_env
        try:
            app.account_access.config_from_env=lambda: {
                "PRIVI_UNIVERSE_OAUTH_ISSUER":"https://id.example.test/",
                "PRIVI_UNIVERSE_OAUTH_AUDIENCE":"privi-universe",
                "PRIVI_UNIVERSE_OAUTH_JWKS":"https://id.example.test/keys",
                "PRIVI_UNIVERSE_BILLING_ISSUER":"https://billing.example.test/",
                "PRIVI_UNIVERSE_BILLING_AUDIENCE":"privi-pro",
                "PRIVI_UNIVERSE_BILLING_JWKS":"https://billing.example.test/keys",
            }
            code,_,body=self.call("GET","/api/access/config")
            self.assertEqual(code,200)
            data=json.loads(body)
            self.assertEqual(data["identity_provider"],"settings_present_unverified")
            self.assertEqual(data["billing_proof"],"settings_present_unverified")
            self.assertEqual(data["browser_login"],"NOT_IMPLEMENTED")
            self.assertEqual(data["privileges"],"DENIED_UNTIL_VERIFIED")
        finally:
            app.account_access.config_from_env=original

    def test_account_and_pro_access_fail_closed_without_idp(self):
        original=app.account_access.config_from_env
        try:
            app.account_access.config_from_env=lambda: {}
            code,_,body=self.call("GET","/api/account/me")
            self.assertEqual(code,503)
            self.assertEqual(json.loads(body)["error"],"identity_provider_not_configured")
            code,_,body=self.call("GET","/api/pro/verify")
            self.assertEqual(code,503)
            code,_,body=self.call("GET","/api/access/config")
            self.assertEqual(code,200)
            obj=json.loads(body)
            self.assertEqual(obj["identity_provider"],"not_configured")
            self.assertEqual(obj["billing_proof"],"not_configured")
            self.assertEqual(obj["browser_login"],"NOT_IMPLEMENTED")
        finally:
            app.account_access.config_from_env=original

    def test_account_route_rejects_missing_token_even_if_configured(self):
        original_config=app.account_access.config_from_env
        original_verify=app.account_access.verify_account_token
        cfg={"PRIVI_UNIVERSE_OAUTH_ISSUER":"https://id.example.test/",
             "PRIVI_UNIVERSE_OAUTH_AUDIENCE":"universe",
             "PRIVI_UNIVERSE_OAUTH_JWKS":"https://id.example.test/keys"}
        try:
            app.account_access.config_from_env=lambda: cfg
            def no_verify(*args,**kwargs):
                raise app.account_access.AccessDenied("Missing token")
            app.account_access.verify_account_token=no_verify
            code,_,body=self.call("GET","/api/account/me")
            self.assertEqual(code,401)
            self.assertEqual(json.loads(body)["error"],"valid_account_access_token_required")
        finally:
            app.account_access.config_from_env=original_config
            app.account_access.verify_account_token=original_verify

    def test_status_endpoint_and_access_disclaimers(self):
        original=app.MONITOR
        try:
            app.MONITOR=app._status_mod.StatusMonitor(
                fetch=lambda url: {"ok":True,"mode":next(
                    expected for fixed,expected in app._status_mod.TARGETS.values()
                    if fixed==url)}, now=lambda:1234)
            status,_,body=self.call("GET","/api/status")
            self.assertEqual(status,200)
            data=json.loads(body)
            self.assertEqual(data["services"]["one"]["state"],"health_responding")
            self.assertEqual(data["services"]["outcome"]["state"],"health_responding")
            self.assertEqual(data["authentication"],"NOT_CONFIGURED")
            self.assertEqual(data["mainnet"],"NOT_CHECKED")
        finally:
            app.MONITOR=original
        self.assertIn("Privi Pro",app.HTML)
        self.assertIn("Not enabled",app.HTML)
        self.assertIn("No passwords",app.HTML)
        self.assertIn("auth-readiness",app.HTML)
        self.assertIn("fetch(\'/api/access/config\'",app.HTML)
        self.assertNotIn('type="password"',app.HTML)
        self.assertIn("Mission status",app.HTML)

    def test_all_modules_have_real_supported_urls(self):
        self.assertEqual(len(app.PRODUCTS),5)
        self.assertEqual(sum(p["mode"]=="demo" for p in app.PRODUCTS),2)
        self.assertEqual(sum(p["mode"]=="reference" for p in app.PRODUCTS),3)
        for p in app.PRODUCTS:
            url=urlsplit(p["href"])
            self.assertEqual(url.scheme,"https")
            self.assertIn(url.netloc,("github.com","privi-one-demo.onrender.com",
                                       "privi-outcomegrid-demo.onrender.com"))
            self.assertNotIn("production",p["status"].lower())
            self.assertIn(p["href"].encode(),app.HTML.encode())
    def test_public_oauth_callback_and_login_stay_disabled(self):
        for path in ("/oauth/start","/oauth/callback","/login","/logout","/api/oauth/exchange","/api/session/create","/api/session/logout"):
            code,_,_=self.call("GET",path)
            self.assertEqual(code,404)
        self.assertIn("Registration and login remain disabled",app.HTML)
        self.assertNotIn("Set-Cookie",app.HTML)

    def test_no_write_or_wallet_endpoint(self):
        for path in ("/wallet","/login","/payments","/mainnet","/api/payouts"):
            status,_,_=self.call("GET",path)
            self.assertEqual(status,404)
            status,_,_=self.call("POST",path)
            self.assertNotEqual(status,200)
    def test_all_reference_cards_explicitly_marked(self):
        for p in app.PRODUCTS:
            card=app.render_card(p)
            if p["mode"]=="reference":
                self.assertIn("SOURCE",card)
                self.assertIn("Explore reference",card)
            else:
                self.assertIn("INTERACTIVE DEMO",card)
                self.assertIn("Launch sandbox",card)
    def test_responsive_and_no_remote_tracking(self):
        self.assertIn("@media(max-width:540px)",app.CSS)
        self.assertIn("prefers-reduced-motion",app.CSS)
        self.assertNotIn("google-analytics.com",app.HTML)
        self.assertIn("fetch('/api/status'",app.HTML)
        self.assertNotIn('type="password"',app.HTML.lower())
        self.assertNotIn("google-analytics.com",app.HTML)

if __name__=="__main__":
    unittest.main()
