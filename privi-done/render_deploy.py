"""Privi DONE read-only Render deployment reporting with pinned service/commit.

Live API GETs only. Status 'live' in Render means it reports deployment
active; it does NOT demonstrate the app meets customer acceptance criteria,
external health checks, or verified costs. No billing, deploy trigger or write.
"""
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import quote

API = "https://api.render.com"
SID = re.compile(r"^srv-[A-Za-z0-9-]{5,100}$")
SHA = re.compile(r"^[a-f0-9]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_BYTES = 2_000_000


class RenderEvidenceUnavailable(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch(path, token):
    if not path.startswith("/v1/services/srv-") or ".." in path or "://" in path:
        raise RenderEvidenceUnavailable("invalid Render read path")
    if not isinstance(token, str) or len(token) < 16:
        raise RenderEvidenceUnavailable("RENDER_API_KEY is required")
    req = Request(API + path, method="GET", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": "Privi-DONE-readonly/0.1"
    })
    try:
        with build_opener(NoRedirect()).open(req, timeout=12) as response:
            if response.geturl() != API + path:
                raise RenderEvidenceUnavailable("unexpected Render redirect")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RenderEvidenceUnavailable("oversized Render response")
            return json.loads(raw)
    except (HTTPError, URLError, TimeoutError, UnicodeError,
            json.JSONDecodeError, OSError) as exc:
        raise RenderEvidenceUnavailable("Render read-only evidence unavailable") from exc


def _github_repo(value):
    """Accept only an exact GitHub URL, never a lookalike domain."""
    if not isinstance(value, str):
        return None
    prefix = "https://github.com/"
    if not value.startswith(prefix):
        return None
    name = value[len(prefix):]
    if name.endswith(".git"):
        name = name[:-4]
    return name if REPO.fullmatch(name) else None


def inspect_deployment(service_id, repository, commit_sha, *, fetch=None):
    """Return reported Render status; no independent execution verification.

    The pinned service ID and repo must be trusted by the caller.
    No arbitrary health URLs accepted. Fetch can be injected in tests only.
    """
    if (not isinstance(service_id, str) or not SID.fullmatch(service_id)
            or not isinstance(repository, str) or not REPO.fullmatch(repository)
            or not isinstance(commit_sha, str) or not SHA.fullmatch(commit_sha)):
        raise RenderEvidenceUnavailable("invalid pinned service/repository/commit")
    transport = fetch if fetch is not None else (
        lambda path: _fetch(path, os.getenv("RENDER_API_KEY")))
    service = transport("/v1/services/" + quote(service_id, safe=""))
    if not isinstance(service, dict) or service.get("id") != service_id:
        raise RenderEvidenceUnavailable("Render service identity mismatch")
    if _github_repo(service.get("repo")) != repository:
        raise RenderEvidenceUnavailable("Render connected repository not pinned or missing")
    entries = transport("/v1/services/{}/deploys?limit=20".format(
        quote(service_id, safe="")))
    if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
        raise RenderEvidenceUnavailable("Render deploy list unavailable or empty")
    deploys = []
    for wrapper in entries:
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get("deploy"), dict):
            raise RenderEvidenceUnavailable("invalid Render deploy entry")
        deploy = wrapper["deploy"]
        commit = deploy.get("commit")
        if (not isinstance(deploy.get("id"), str) or not deploy["id"]
                or not isinstance(deploy.get("status"), str)
                or not isinstance(commit, dict)
                or not isinstance(commit.get("id"), str)
                or not SHA.fullmatch(commit["id"])
                or not isinstance(deploy.get("createdAt"), str)
                or not deploy["createdAt"]):
            raise RenderEvidenceUnavailable("invalid Render Git deploy metadata")
        deploys.append(deploy)
    if len({d["id"] for d in deploys}) != len(deploys):
        raise RenderEvidenceUnavailable("duplicate Render deploy IDs")
    # Sort by Render-reported timestamp, not by untrusted API list order.
    deploys.sort(key=lambda d: (d["createdAt"], d["id"]), reverse=True)
    most_recent = deploys[0]
    live = [d for d in deploys if d["status"] == "live"]
    conditions = (
        most_recent["status"] == "live"
        and most_recent["commit"]["id"] == commit_sha
        and len(live) == 1
    )
    return {
        "schema": "privi-done-render-v1",
        "service_id": service_id,
        "repository": repository,
        "expected_commit": commit_sha,
        "observed_commit": most_recent["commit"]["id"],
        "latest_deploy_id": most_recent["id"],
        "latest_status": most_recent["status"],
        "reported_live_commit_matches": conditions,
        "result": "RENDER_REPORTS_LIVE_COMMIT_HEALTH_UNVERIFIED"
            if conditions else "RENDER_DEPLOY_UNVERIFIED",
        "independent_health_verified": False,
        "cost_verified": False,
        "customer_outcome_certified": False
    }
