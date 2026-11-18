"""Privi DONE: offline, fail-closed software deployment outcome assessment.

All inputs are untrusted snapshots unless retrieved independently by a
separately authenticated integration. This code makes NO API/network calls,
executes no code, pays nobody, and never grants an entitlement. Even a passing
snapshot is pending independent verification, not proof of completed work.
"""
import hashlib
import json
import re

_SHA = re.compile(r"^[a-f0-9]{40}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_CHECK_STATUS = {"success", "failure", "cancelled", "pending", "skipped"}


def _canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def assess_deployment(intent, evidence):
    """Review pinned identity, checks, sample probes, and synthetic cost cap.

    A 'pass' is only a local assessment of caller-provided evidence. It never
    asserts that external systems were queried or independently validated.
    """
    if not isinstance(intent, dict) or not isinstance(evidence, dict):
        raise ValueError("intent and evidence must be objects")
    if set(intent) != {"repository", "commit_sha", "required_checks",
                       "expected_version", "max_cost_cents"}:
        raise ValueError("invalid intent schema")
    repo, sha = intent["repository"], intent["commit_sha"]
    required = intent["required_checks"]
    if (not isinstance(repo, str) or not _REPO.fullmatch(repo)
            or not isinstance(sha, str) or not _SHA.fullmatch(sha)
            or not isinstance(required, list) or not required
            or any(not isinstance(v, str) or not v.strip() for v in required)
            or len(required) != len(set(required))
            or not isinstance(intent["expected_version"], str)
            or not intent["expected_version"]
            or type(intent["max_cost_cents"]) is not int
            or not 0 <= intent["max_cost_cents"] <= 100_000_000):
        raise ValueError("invalid deployment intent values")
    if set(evidence) != {"repository", "commit_sha", "checks",
                         "observed_version", "probes", "cost_cents", "complete"}:
        raise ValueError("invalid evidence schema")
    if type(evidence["complete"]) is not bool:
        raise ValueError("evidence completeness must be boolean")
    checks, probes = evidence["checks"], evidence["probes"]
    if (not isinstance(checks, list) or not isinstance(probes, list)
            or not all(isinstance(x, dict) and set(x) == {"name", "conclusion"} for x in checks)
            or not all(isinstance(x.get("name"), str) and x.get("name")
                       and x.get("conclusion") in _CHECK_STATUS for x in checks)
            or len({x["name"] for x in checks}) != len(checks)
            or not all(isinstance(x, dict)
                       and set(x) == {"name", "passed"} and isinstance(x["name"], str)
                       and x["name"] and type(x["passed"]) is bool for x in probes)
            or len({x["name"] for x in probes}) != len(probes)
            or type(evidence["cost_cents"]) is not int
            or evidence["cost_cents"] < 0):
        raise ValueError("invalid evidence values")
    failures = []
    if evidence["repository"] != repo or evidence["commit_sha"] != sha:
        failures.append("pinned-repository-or-commit-mismatch")
    if not evidence["complete"]:
        failures.append("incomplete-evidence")
    by_name = {x["name"]: x["conclusion"] for x in checks}
    for required_name in required:
        if by_name.get(required_name) != "success":
            failures.append("required-check-not-success:" + required_name)
    if evidence["observed_version"] != intent["expected_version"]:
        failures.append("deployed-version-mismatch")
    if not probes:
        failures.append("no-deployment-probes")
    for probe in probes:
        if not probe["passed"]:
            failures.append("probe-failed:" + probe["name"])
    if evidence["cost_cents"] > intent["max_cost_cents"]:
        failures.append("cost-cap-exceeded")
    assessment = {
        "schema": "privi-done-offline-v1",
        "result": "FAIL" if failures else "PASS_PENDING_INDEPENDENT_VERIFICATION",
        "issues": failures,
        "repository": repo, "commit_sha": sha,
        "claimed_cost_cents": evidence["cost_cents"],
        "independent_execution_verified": False,
        "payment_verified": False,
        "customer_outcome_certified": False,
    }
    assessment["sha256"] = hashlib.sha256(
        b"PRIVI-DONE-OFFLINE-REVIEW-v1\x00" + _canonical(assessment)
    ).hexdigest()
    return assessment
