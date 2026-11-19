"""Read-only self-reported running version check for fixed Privi ONE sandbox.

No arbitrary URL or GitHub commit is accepted. A version match is a
correlation of a server self-report with a pinned Render commit, NOT a
cryptographic proof that the expected code is executing.
"""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler

URL = "https://privi-one-demo.onrender.com/api/version"
SHA = re.compile(r"^[a-f0-9]{40}$")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read():
    req = Request(URL, method="GET", headers={
        "Accept": "application/json",
        "User-Agent": "Privi-DONE-version-observer/0.1",
    })
    with build_opener(NoRedirect()).open(req, timeout=45) as response:
        if response.status != 200 or response.geturl() != URL:
            raise ValueError("unexpected version endpoint response")
        raw = response.read(4097)
        if len(raw) > 4096:
            raise ValueError("oversized version response")
        return json.loads(raw)


def inspect_version(expected_commit, *, read=None):
    if not isinstance(expected_commit, str) or not SHA.fullmatch(expected_commit):
        raise ValueError("exact pinned SHA required")
    try:
        value = _read() if read is None else read()
    except (HTTPError, URLError, OSError, TimeoutError, ValueError,
            UnicodeError, TypeError):
        value = None
    valid = (
        isinstance(value, dict)
        and set(value) == {"service", "mode", "version_source",
                           "self_reported_commit", "independently_attested"}
        and value.get("service") == "privi-one-demo"
        and value.get("mode") == "PRELAUNCH_SIMULATION"
        and value.get("version_source") == "RENDER_GIT_COMMIT_ENV"
        and value.get("independently_attested") is False
        and value.get("self_reported_commit") == expected_commit
    )
    return {
        "schema": "privi-done-version-observation-v1",
        "endpoint": URL,
        "expected_commit": expected_commit,
        "server_self_report_matches": bool(valid),
        "result": "SELF_REPORTED_VERSION_MATCH_UNATTESTED"
            if valid else "VERSION_MISMATCH_OR_UNAVAILABLE",
        "execution_cryptographically_attested": False,
        "customer_outcome_certified": False,
    }
