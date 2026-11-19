"""Privi Universe service status health checks: fixed URLs and fail-closed."""
import importlib.util
from pathlib import Path
import threading
import unittest

path=Path(__file__).with_name("status_monitor.py")
spec=importlib.util.spec_from_file_location("universe_status_test",path)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MonitorTests(unittest.TestCase):
    def test_healthy_models_only(self):
        now=[100]
        calls=[]
        def fetch(url):
            calls.append(url)
            expected=next(v[1] for v in m.TARGETS.values() if v[0]==url)
            return {"ok":True,"mode":expected}
        mon=m.StatusMonitor(fetch=fetch,now=lambda:now[0])
        a=mon.snapshot()
        self.assertEqual(a["services"]["one"]["state"],"health_responding")
        self.assertEqual(a["services"]["outcome"]["state"],"health_responding")
        self.assertEqual(len(calls),2)
        self.assertEqual(mon.snapshot(),a)
        self.assertEqual(len(calls),2)
        now[0]+=m.CACHE_SECONDS+1
        self.assertEqual(mon.snapshot()["checked_at_unix"],now[0])
        self.assertEqual(len(calls),4)

    def test_fail_closed_and_reference_not_monitored(self):
        def fetch(url):
            if "outcomegrid" in url:
                raise ConnectionError("synthetic failure")
            return {"ok":True,"mode":"PRODUCTION"}
        a=m.StatusMonitor(fetch=fetch,now=lambda:10).snapshot()
        self.assertEqual(a["services"]["one"]["state"],"unexpected_health_response")
        self.assertEqual(a["services"]["outcome"]["state"],"unreachable_or_unverified")
        self.assertEqual(a["references"]["ledger"],"not_monitored_source_reference")
        self.assertEqual(a["mainnet"],"NOT_CHECKED")
        self.assertEqual(a["payments"],"NOT_CHECKED")

    def test_https_allowlist(self):
        with self.assertRaises(ValueError):
            m.https_fetch("http://localhost/health")
        with self.assertRaises(ValueError):
            m.https_fetch("https://example.com/health")

    def test_concurrent_calls_shared_cache(self):
        count=[0]
        def fetch(url):
            count[0]+=1
            return {"ok":True,"mode":next(v[1] for v in m.TARGETS.values() if v[0]==url)}
        mon=m.StatusMonitor(fetch=fetch,now=lambda:123)
        threads=[threading.Thread(target=mon.snapshot) for _ in range(12)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(count[0],2)


if __name__=="__main__":
    unittest.main()
