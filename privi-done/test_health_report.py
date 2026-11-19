"""Safety checks for optional pinned public-health observation in reports."""
import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).with_name("provider_report.py")
spec=importlib.util.spec_from_file_location("privi_done_report_with_health",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

REPO="example/hello"
SHA="a"*40
SID="srv-example123"
CHECKS=["build"]
GH={"schema":"privi-done-github-checks-v1","repository":REPO,
    "commit_sha":SHA,"source":"github-check-runs-api",
    "result":"REPORTED_CHECKS_SUCCESS_DEPLOYMENT_UNVERIFIED",
    "deployment_verified":False,"cost_verified":False,
    "required_checks":[{"name":"build","result":"success","run_id":1}]}
RD={"schema":"privi-done-render-v1","repository":REPO,
    "expected_commit":SHA,"observed_commit":SHA,"service_id":SID,
    "latest_status":"live","reported_live_commit_matches":True,
    "result":"RENDER_REPORTS_LIVE_COMMIT_HEALTH_UNVERIFIED",
    "independent_health_verified":False,"cost_verified":False}
HEALTH={"schema":"privi-done-public-health-v1",
        "endpoint":"https://privi-one-demo.onrender.com/health",
        "result":"PRIVI_ONE_SANDBOX_HEALTH_REPORTED",
        "http_health_reported":True,
        "expected_commit_verified":False,
        "customer_outcome_certified":False}


class HealthReportTests(unittest.TestCase):
    def report(self, health):
        return m.assess_provider_reports(REPO,SHA,SID,CHECKS,GH,RD,
                                         health_report=health)

    def test_valid_health_still_never_certs_completion(self):
        result=self.report(HEALTH)
        self.assertTrue(result["privi_one_sandbox_health_reported"])
        self.assertFalse(result["completed"])
        self.assertFalse(result["invoiceable_as_verified_outcome"])
        self.assertIn("independent-service-health-unverified",result["issues"])
        md=m.render_customer_markdown(result)
        self.assertIn("Observed (not commit-specific)",md)
        self.assertIn("Not certified as completed",md)

    def test_unchecked_vs_failed_distinguished(self):
        self.assertIsNone(self.report(None)["privi_one_sandbox_health_reported"])
        bad=dict(HEALTH,result="HEALTH_UNAVAILABLE",http_health_reported=False)
        self.assertFalse(self.report(bad)["privi_one_sandbox_health_reported"])

    def test_forged_commit_and_outcome_flags_rejected(self):
        for key in ("expected_commit_verified","customer_outcome_certified"):
            with self.subTest(key=key):
                fake=dict(HEALTH)
                fake[key]=True
                self.assertFalse(self.report(fake)["privi_one_sandbox_health_reported"])

    def test_other_endpoint_not_accepted(self):
        fake=dict(HEALTH,endpoint="https://untrusted.example/health")
        self.assertFalse(self.report(fake)["privi_one_sandbox_health_reported"])


if __name__=="__main__":
    unittest.main()
