"""Read-only health evidence for the pinned Privi ONE public sandbox.

Only a hardcoded company-owned demo endpoint is supported. No caller URL,
redirect following, DNS/host customization, arbitrary requests, or secrets.
A health response confirms a limited HTTP observation, not that a customer's
deployment is complete or that a specific Git commit is deployed.
"""
import json
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError

HEALTH_URL = "https://privi-one-demo.onrender.com/health"
EXPECTED_SERVICE = "privi-one-demo"
EXPECTED_MODE = "PRELAUNCH_SIMULATION"


class HealthUnavailable(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _live_read():
    request = Request(HEALTH_URL, method="GET", headers={
        "Accept": "application/json",
        "User-Agent": "Privi-DONE-sandbox-observer/0.1",
    })
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            if response.status != 200 or response.geturl() != HEALTH_URL:
                raise HealthUnavailable("unexpected health response")
            raw = response.read(4097)
            if len(raw) > 4096:
                raise HealthUnavailable("oversized health response")
            return json.loads(raw)
    except (HTTPError, URLError, TimeoutError, OSError,
            ValueError, UnicodeError) as exc:
        raise HealthUnavailable("Privi sandbox health unavailable") from exc


def inspect_privi_one_health(*, read=None):
    """Report only exactly observed sandbox health; no onchain/version claim."""
    try:
        response = _live_read() if read is None else read()
    except (HealthUnavailable, TimeoutError, OSError, ValueError):
        return {
            "schema": "privi-done-public-health-v1",
            "endpoint": HEALTH_URL,
            "result": "HEALTH_UNAVAILABLE",
            "http_health_reported": False,
            "expected_commit_verified": False,
            "customer_outcome_certified": False,
        }
    okay = (isinstance(response, dict)
            and response.get("ok") is True
            and response.get("service") == EXPECTED_SERVICE
            and response.get("mode") == EXPECTED_MODE)
    return {
        "schema": "privi-done-public-health-v1",
        "endpoint": HEALTH_URL,
        "result": "PRIVI_ONE_SANDBOX_HEALTH_REPORTED" if okay else "HEALTH_MISMATCH",
        "http_health_reported": bool(okay),
        "expected_commit_verified": False,
        "customer_outcome_certified": False,
    }
