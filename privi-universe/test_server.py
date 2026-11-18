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
        self.assertNotIn("<script",app.HTML.lower())

if __name__=="__main__":
    unittest.main()
