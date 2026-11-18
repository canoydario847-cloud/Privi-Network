"""Read-only GitHub check-run evidence collector for OutcomeGrid (prelaunch).

Fetches authenticated GitHub REST API snapshots for a pinned owner/repository
and exact 40-char commit SHA. No POST, no repository mutation, no agent
execution, no automatic outcome credit and no PRVI/payment operations.

Not wired into the public Render demo. The runner must supply a GitHub token
through its environment; NEVER provide a token to the public demo or logs.
"""
from __future__ import annotations

import json
import os
import re
import ssl
from urllib.parse import quote, urlsplit, parse_qs
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

from github_evidence import REPO, SHA, verify_check_runs

API = "https://api.github.com"
MAX_PAGES = 10
PAGE_SIZE = 100


class DenyRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Unexpected GitHub API redirect")


def collect(repo, head_sha, *, allowed_repo, token, get_json=None):
    """Return conservatively pinned REST evidence, without accepting job claims.

    get_json is an injectable *trusted test transport*; never set it from a
    public request. In production it must be the authenticated GitHub fetcher.
    """
    if not isinstance(repo, str) or not REPO.fullmatch(repo):
        raise ValueError("Invalid repository")
    if not isinstance(head_sha, str) or not SHA.fullmatch(head_sha):
        raise ValueError("Commit must be a pinned 40-char lowercase SHA-1")
    if repo != allowed_repo:
        raise PermissionError("Repository not explicitly allowlisted")
    if not isinstance(token, str) or len(token) < 12:
        raise PermissionError("GitHub read-only token required")
    if get_json is None:
        opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), DenyRedirects())
        def get_json(url):
            req = Request(url, headers={
                "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "privi-outcomegrid-sandbox",
            }, method="GET")
            with opener.open(req, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError("GitHub API did not return 200")
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise RuntimeError("GitHub API response exceeds limit")
                return json.loads(raw)
    base = (API + "/repos/" + quote(repo.split("/")[0], safe="") + "/" +
            quote(repo.split("/")[1], safe="") + "/commits/" + head_sha +
            "/check-runs")
    results = []
    expected_total = None
    for page in range(1, MAX_PAGES + 1):
        url = base + "?per_page=" + str(PAGE_SIZE) + "&page=" + str(page)
        # Construct URLs ourselves; never follow a Link URL or user-supplied host.
        payload = get_json(url)
        if not isinstance(payload, dict) or type(payload.get("total_count")) is not int:
            raise RuntimeError("Invalid GitHub API response")
        count = payload["total_count"]
        if count < 0 or count > MAX_PAGES * PAGE_SIZE:
            raise RuntimeError("Too many check runs for bounded evidence collector")
        if expected_total is None:
            expected_total = count
        if count != expected_total:
            raise RuntimeError("Check run count changed while paging; retry later")
        runs = payload.get("check_runs")
        if not isinstance(runs, list) or len(runs) > PAGE_SIZE:
            raise RuntimeError("Invalid GitHub check-runs page")
        results.extend(runs)
        if len(results) >= expected_total:
            break
        if not runs:
            raise RuntimeError("GitHub response ended before all pages were read")
    if len(results) != expected_total:
        raise RuntimeError("Incomplete GitHub check-run pagination")
    # Repository is bound to the requested path, and SHA to the requested
    # commit; all qualifying check-run SHA fields are revalidated downstream.
    return {"repository": repo, "head_sha": head_sha,
            "total_count": expected_total, "check_runs": results,
            "source": "GITHUB_REST_AUTHENTICATED_FETCH_NOT_SIGNED_API_ATTESTATION"}


def collect_and_review(repo, head_sha, required_checks, *, allowed_repo, token, get_json=None):
    snapshot = collect(repo, head_sha, allowed_repo=allowed_repo,
                       token=token, get_json=get_json)
    return verify_check_runs(snapshot, repo=repo, head_sha=head_sha,
                             required_checks=required_checks)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="Exact allowlisted owner/repo")
    parser.add_argument("--sha", required=True, help="Pinned full commit SHA")
    parser.add_argument("--required-check", action="append", required=True)
    args = parser.parse_args()
    allow = os.environ.get("OUTCOMEGRID_ALLOWED_GITHUB_REPO", "")
    token = os.environ.get("OUTCOMEGRID_GITHUB_READ_TOKEN", "")
    result = collect_and_review(args.repo, args.sha, args.required_check,
                                allowed_repo=allow, token=token)
    print(json.dumps(result, indent=2))
    # Only an evidence candidate is produced; no automatic acceptance.
    return 0 if result.get("valid") else 2


if __name__ == "__main__":
    raise SystemExit(main())
