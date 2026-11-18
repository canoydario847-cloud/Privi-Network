"""OutcomeGrid GitHub evidence validator for trusted, separately fetched API snapshots.

Pure offline parsing: callers MUST fetch responses from authenticated GitHub
REST API over TLS themselves and verify repository identity and authorization.
An arbitrary JSON document is NOT proof it came from GitHub. This module
does not grant verifier identity, authorize money, or auto-credit outcomes.
"""
from __future__ import annotations

import hashlib
import json
import re

REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
SHA = re.compile(r"^[a-f0-9]{40}$")
ALLOWED_STATES = {"success", "failure", "neutral", "cancelled", "timed_out", "action_required", "skipped"}


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def verify_check_runs(snapshot, *, repo, head_sha, required_checks):
    """Validate fields of a previously authenticated GitHub check-runs response.

    Returns digest and a conservative result for independent review, not a
    trust assertion or final acceptance decision.
    """
    if not isinstance(repo, str) or not REPO.fullmatch(repo):
        raise ValueError("invalid repository")
    if not isinstance(head_sha, str) or not SHA.fullmatch(head_sha):
        raise ValueError("invalid pinned commit SHA")
    if (not isinstance(required_checks, (list, tuple)) or not required_checks
            or any(not isinstance(x, str) or not x or len(x) > 120 for x in required_checks)
            or len(set(required_checks)) != len(required_checks)):
        raise ValueError("required check names must be unique")
    if not isinstance(snapshot, dict):
        raise ValueError("invalid check run snapshot")
    # Caller must bind repo and commit to the job before fetching. Snapshot fields
    # are insufficient to authenticate an API response by themselves.
    if snapshot.get("repository") != repo or snapshot.get("head_sha") != head_sha:
        return {"valid": False, "reason": "repository_or_commit_mismatch"}
    runs = snapshot.get("check_runs")
    if not isinstance(runs, list) or len(runs) > 1000:
        return {"valid": False, "reason": "invalid_check_runs"}
    if snapshot.get("total_count") != len(runs):
        # Reject incomplete pagination / missing required evidence.
        return {"valid": False, "reason": "incomplete_check_run_snapshot"}
    found = {}
    for run in runs:
        if not isinstance(run, dict):
            return {"valid": False, "reason": "invalid_check_run"}
        name = run.get("name")
        if name not in required_checks:
            continue
        if name in found:
            # Duplicate names can be misleading: require a uniquely pinned run.
            return {"valid": False, "reason": "ambiguous_check_name"}
        if run.get("head_sha") != head_sha:
            return {"valid": False, "reason": "check_commit_mismatch"}
        if run.get("status") != "completed":
            return {"valid": False, "reason": "check_not_complete"}
        conclusion = run.get("conclusion")
        if conclusion not in ALLOWED_STATES:
            return {"valid": False, "reason": "unknown_check_conclusion"}
        if not isinstance(run.get("id"), int) or run["id"] <= 0:
            return {"valid": False, "reason": "missing_check_run_id"}
        if not isinstance(run.get("app"), dict) or not isinstance(run["app"].get("slug"), str):
            return {"valid": False, "reason": "unidentified_check_app"}
        found[name] = {"run_id": run["id"], "app_slug": run["app"]["slug"],
                       "conclusion": conclusion}
    if set(found) != set(required_checks):
        return {"valid": False, "reason": "required_checks_missing",
                "missing": sorted(set(required_checks) - set(found))}
    if any(row["conclusion"] != "success" for row in found.values()):
        return {"valid": False, "reason": "required_check_not_successful"}
    return {
        "valid": True,
        "state": "checks_passed_awaiting_independent_review",
        "repository": repo,
        "head_sha": head_sha,
        "required_checks": found,
        "snapshot_sha256": hashlib.sha256(canonical(snapshot)).hexdigest(),
        "source_authentication": "CALLER_MUST_VERIFY_GITHUB_API_ORIGIN",
        "scoreboard_eligible": False,
    }
