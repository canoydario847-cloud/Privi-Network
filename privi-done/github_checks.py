"""Read-only GitHub check-run evidence collector for Privi DONE.

Fetches from GitHub API at a fixed origin and exact pinned commit. This
authenticates GitHub's *reporting* of checks over TLS, not execution outcomes,
deployment version, price, external endpoint health, or author identity.

No credentials logged, no arbitrary URLs/SSRF, no writes, no payment access.
"""
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA = re.compile(r"^[a-f0-9]{40}$")
API = "https://api.github.com"
MAX_PAGES = 20
PAGE_SIZE = 100


class EvidenceUnavailable(ValueError):
    pass


def _request(path, *, token=None):
    """Fixed GitHub API origin, read-only GET. No caller-provided URL."""
    if not path.startswith("/repos/") or ".." in path or "://" in path:
        raise EvidenceUnavailable("invalid GitHub API path")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Privi-DONE-readonly-checks/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(API + path, headers=headers, method="GET")
    try:
        # urllib may follow redirects; none are expected from GitHub checks.
        with urlopen(req, timeout=12) as response:
            if response.geturl() != API + path:
                raise EvidenceUnavailable("unexpected API redirect")
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise EvidenceUnavailable("oversized GitHub API response")
            return json.loads(raw)
    except (HTTPError, URLError, TimeoutError, UnicodeError,
            json.JSONDecodeError, OSError) as exc:
        raise EvidenceUnavailable("GitHub check runs unavailable") from exc


def collect_checks(repository, commit_sha, required_checks, *, fetch=None):
    """Return verified-source GitHub check evidence; never certify deployment.

    `fetch` is an injectable test transport and MUST NOT be exposed to
    untrusted requests in production. Same-name runs are rejected: a separate
    trusted policy must define workflow/app identity and retry supersession.
    """
    if (not isinstance(repository, str) or not REPO.fullmatch(repository)
            or not isinstance(commit_sha, str) or not SHA.fullmatch(commit_sha)
            or not isinstance(required_checks, list) or not required_checks
            or any(not isinstance(n, str) or not n.strip()
                   or len(n) > 200 for n in required_checks)
            or len(set(required_checks)) != len(required_checks)):
        raise EvidenceUnavailable("invalid pinned repository, SHA or required checks")
    owner, name = repository.split("/")
    root = "/repos/{}/{}/commits/{}/check-runs".format(
        quote(owner, safe=""), quote(name, safe=""), commit_sha)
    transport = fetch if fetch is not None else (
        lambda path: _request(path, token=os.environ.get("GITHUB_TOKEN")))
    runs = []
    total = None
    for page in range(1, MAX_PAGES + 1):
        path = root + "?per_page={}&page={}".format(PAGE_SIZE, page)
        payload = transport(path)
        if (not isinstance(payload, dict)
                or type(payload.get("total_count")) is not int
                or not 0 <= payload["total_count"] <= MAX_PAGES * PAGE_SIZE
                or not isinstance(payload.get("check_runs"), list)
                or len(payload["check_runs"]) > PAGE_SIZE):
            raise EvidenceUnavailable("invalid or excessive GitHub page")
        if total is None:
            total = payload["total_count"]
        elif total != payload["total_count"]:
            raise EvidenceUnavailable("check results changed during pagination")
        chunk = payload["check_runs"]
        if len(chunk) != min(PAGE_SIZE, max(0, total - len(runs))):
            raise EvidenceUnavailable("incomplete check results pagination")
        runs.extend(chunk)
        if len(runs) == total:
            break
    if len(runs) != total:
        raise EvidenceUnavailable("incomplete check results pagination")
    names = {}
    for run in runs:
        if (not isinstance(run, dict)
                or not isinstance(run.get("name"), str) or not run["name"]
                or run.get("head_sha") != commit_sha
                or run.get("status") not in ("queued", "in_progress", "completed")
                or run.get("conclusion") not in (
                    None, "success", "failure", "neutral", "cancelled",
                    "skipped", "timed_out", "action_required", "startup_failure")
                or type(run.get("id")) is not int or run["id"] <= 0):
            raise EvidenceUnavailable("malformed or incorrectly pinned check run")
        if run["name"] in names:
            raise EvidenceUnavailable("duplicate check name; ambiguous result")
        names[run["name"]] = run

    status = []
    for check in required_checks:
        run = names.get(check)
        outcome = ("missing" if run is None else
                   "success" if run["status"] == "completed"
                   and run["conclusion"] == "success" else "not-success")
        status.append({"name": check, "result": outcome,
                       "run_id": None if run is None else run["id"]})
    return {
        "schema": "privi-done-github-checks-v1",
        "source": "github-check-runs-api",
        "repository": repository, "commit_sha": commit_sha,
        "required_checks": status,
        "check_count": len(runs),
        "result": "REPORTED_CHECKS_SUCCESS_DEPLOYMENT_UNVERIFIED"
            if all(item["result"] == "success" for item in status) else
            "FAIL_CI_EVIDENCE",
        "deployment_verified": False,
        "cost_verified": False,
        "author_verified": False,
    }
