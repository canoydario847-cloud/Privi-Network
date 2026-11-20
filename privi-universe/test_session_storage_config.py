"""Session-storage configuration safety: zero external DB traffic."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location(
    "universe_storage_config",Path(__file__).with_name("session_storage_config.py"))
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

GOOD = {
  "PRIVI_UNIVERSE_SESSION_BACKEND":"postgres",
  "PRIVI_UNIVERSE_SESSION_DATABASE_URL":"postgresql://session_owner:example-pass@sessiondb.example.test:5432/privi_universe_sessions?sslmode=verify-full",
  "PRIVI_UNIVERSE_SESSION_SCHEMA":"privi_sessions",
  "PRIVI_UNIVERSE_SESSION_ADMIN_REVIEWED":"true",
  "PRIVI_UNIVERSE_SESSION_BACKUPS_VERIFIED":"true",
}

class SessionStoragePreflightTests(unittest.TestCase):
    def test_default_fail_closed(self):
        r=m.check_session_storage({})
        self.assertFalse(r["ready"])
        self.assertEqual(r["reason"],"session_backend_not_enabled")
    def test_hard_block_billing_databases(self):
        for name in ["privi_billing_staging","privi_billing_production",
                     "a_stripe_orders","privi_payment_data","privi_ledger"]:
            cfg=dict(GOOD,PRIVI_UNIVERSE_SESSION_DATABASE_URL=
                     "postgresql://u:password@db.test:5432/"+name+"?sslmode=verify-full")
            result=m.check_session_storage(cfg)
            self.assertFalse(result["ready"])
            self.assertEqual(result["reason"],"billing_database_is_not_session_storage")
    def test_tls_and_connection_options(self):
        for options in ["sslmode=require","sslmode=disable",
                        "sslmode=verify-full&options=-c%20search_path%3Dpublic"]:
            cfg=dict(GOOD,PRIVI_UNIVERSE_SESSION_DATABASE_URL=
                     "postgresql://u:password@db.test:5432/privi_universe_sessions?"+options)
            self.assertFalse(m.check_session_storage(cfg)["ready"])
    def test_review_and_backups_required(self):
        for k in ("PRIVI_UNIVERSE_SESSION_SCHEMA","PRIVI_UNIVERSE_SESSION_ADMIN_REVIEWED",
                  "PRIVI_UNIVERSE_SESSION_BACKUPS_VERIFIED"):
            bad=dict(GOOD)
            bad.pop(k)
            self.assertFalse(m.check_session_storage(bad)["ready"])
    def test_no_credentials_exposed_on_ready_or_error(self):
        self.assertEqual(m.check_session_storage(GOOD),
                         {"ready":True,"reason":"configuration_present_unverified_connectivity"})
        bad=dict(GOOD,PRIVI_UNIVERSE_SESSION_DATABASE_URL="postgresql://hello:verysecret@db.test")
        result=m.check_session_storage(bad)
        self.assertFalse(result["ready"])
        self.assertNotIn("verysecret",str(result))
        self.assertNotIn("hello",str(result))
    def test_invalid_urls_rejected(self):
        for url in ["", "sqlite:///abc.db",
                    "postgresql://u:pw@db.test/privi_sessions?sslmode=verify-full#frag",
                    "postgresql://u@db.test/privi_sessions?sslmode=verify-full",
                    "postgresql://u:pw@db.test:bad/privi_sessions?sslmode=verify-full"]:
            cfg=dict(GOOD,PRIVI_UNIVERSE_SESSION_DATABASE_URL=url)
            self.assertFalse(m.check_session_storage(cfg)["ready"])

if __name__=="__main__":
    unittest.main()
