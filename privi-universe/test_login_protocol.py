"""Privi Universe OAuth PKCE transaction security regressions, no IdP calls."""
import importlib.util
from pathlib import Path
import threading
import unittest

path=Path(__file__).with_name("login_protocol.py")
spec=importlib.util.spec_from_file_location("universe_login_proto_tests",path)
login=importlib.util.module_from_spec(spec)
spec.loader.exec_module(login)

ISSUER="https://login.example.test/"
REDIRECT="https://privi-universe-demo.onrender.com/oauth/callback"


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.clock=[1000]
        self.store=login.LoginTransactions(now=lambda:self.clock[0])

    def issue(self):
        return self.store.issue(issuer=ISSUER,redirect_uri=REDIRECT)

    def test_s256_state_and_single_use(self):
        request=self.issue()
        self.assertEqual(request["code_challenge_method"],"S256")
        self.assertEqual(len(request["code_challenge"]),43)
        result=self.store.consume(request["state"],issuer=ISSUER,redirect_uri=REDIRECT)
        self.assertEqual(login.s256_challenge(result["code_verifier"]),request["code_challenge"])
        self.assertEqual(result["nonce"],request["nonce"])
        with self.assertRaises(ValueError):
            self.store.consume(request["state"],issuer=ISSUER,redirect_uri=REDIRECT)

    def test_wrong_issuer_redirect_consumes_state(self):
        for kwargs in ({"issuer":"https://evil.example/","redirect_uri":REDIRECT},
                       {"issuer":ISSUER,"redirect_uri":"https://evil.example/callback"}):
            request=self.issue()
            with self.assertRaises(ValueError):
                self.store.consume(request["state"],**kwargs)
            with self.assertRaises(ValueError):
                self.store.consume(request["state"],issuer=ISSUER,redirect_uri=REDIRECT)

    def test_expiration_denied(self):
        request=self.issue()
        self.clock[0]+=login.TTL_SECONDS
        with self.assertRaises(ValueError):
            self.store.consume(request["state"],issuer=ISSUER,redirect_uri=REDIRECT)

    def test_reject_bad_redirect_and_verifier(self):
        with self.assertRaises(ValueError):
            self.store.issue(issuer=ISSUER,redirect_uri="http://localhost/callback")
        with self.assertRaises(ValueError):
            self.store.issue(issuer=ISSUER,redirect_uri="https://attacker@provider.example/cb")
        with self.assertRaises(ValueError):
            login.s256_challenge("too-short")

    def test_max_pending_prevents_memory_exhaustion(self):
        for i in range(login.MAX_PENDING):
            self.issue()
        with self.assertRaises(RuntimeError):
            self.issue()
        self.clock[0]+=login.TTL_SECONDS+1
        self.issue()

    def test_concurrent_state_replay_one_winner(self):
        state=self.issue()["state"]
        success=[]
        lock=threading.Lock()
        def worker():
            try:
                self.store.consume(state,issuer=ISSUER,redirect_uri=REDIRECT)
                valid=True
            except ValueError:
                valid=False
            with lock:
                success.append(valid)
        threads=[threading.Thread(target=worker) for _ in range(20)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(success.count(True),1)
        self.assertEqual(success.count(False),19)


if __name__=="__main__":
    unittest.main()
