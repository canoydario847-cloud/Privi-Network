"""Privi DONE: combined GitHub/Render deployment evidence report.

The GitHub and Render collectors read provider-reported metadata independently
but do not prove running service health, actual billing, independent execution,
or customer acceptance. Deliberately no success/paid/completed status.
"""
import hashlib
import json
import re

SHA = re.compile(r"^[a-f0-9]{40}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def assess_provider_reports(repository, commit_sha, service_id, required_checks,
                            github_report, render_report, *, health_report=None):
    """Correlate exact identities, explicit results and conservative claims.

    Provider reports should come from trusted collector code, never from
    customer-submitted JSON. Even matched reports remain INCOMPLETE without
    independent health/cost/acceptance verification.
    """
    if (not isinstance(repository, str) or not REPO.fullmatch(repository)
            or not isinstance(commit_sha, str) or not SHA.fullmatch(commit_sha)
            or not isinstance(service_id, str) or not service_id.startswith("srv-")
            or not isinstance(required_checks, list) or not required_checks
            or any(not isinstance(n, str) or not n for n in required_checks)
            or len(required_checks) != len(set(required_checks))
            or not isinstance(github_report, dict) or not isinstance(render_report, dict)):
        raise ValueError("invalid or unpinned report inputs")
    gh = (github_report.get("schema") == "privi-done-github-checks-v1"
          and github_report.get("repository") == repository
          and github_report.get("commit_sha") == commit_sha
          and github_report.get("source") == "github-check-runs-api"
          and github_report.get("result") == "REPORTED_CHECKS_SUCCESS_DEPLOYMENT_UNVERIFIED"
          and github_report.get("deployment_verified") is False
          and github_report.get("cost_verified") is False)
    checks = github_report.get("required_checks")
    gh = (gh and isinstance(checks, list)
          and len(checks) == len(required_checks)
          and all(isinstance(x, dict) and set(x) == {"name", "result", "run_id"}
                  and x.get("name") == n and x.get("result") == "success"
                  and type(x.get("run_id")) is int and x["run_id"] > 0
                  for x, n in zip(checks, required_checks)))
    rd = (render_report.get("schema") == "privi-done-render-v1"
          and render_report.get("repository") == repository
          and render_report.get("expected_commit") == commit_sha
          and render_report.get("observed_commit") == commit_sha
          and render_report.get("service_id") == service_id
          and render_report.get("latest_status") == "live"
          and render_report.get("reported_live_commit_matches") is True
          and render_report.get("result") == "RENDER_REPORTS_LIVE_COMMIT_HEALTH_UNVERIFIED"
          and render_report.get("independent_health_verified") is False
          and render_report.get("cost_verified") is False)
    issues = []
    if not gh:
        issues.append("github-required-checks-not-verified")
    if not rd:
        issues.append("render-deploy-not-verified")
    health = None
    if health_report is not None:
        health = (isinstance(health_report, dict)
                  and health_report.get("schema") == "privi-done-public-health-v1"
                  and health_report.get("endpoint") == "https://privi-one-demo.onrender.com/health"
                  and health_report.get("result") == "PRIVI_ONE_SANDBOX_HEALTH_REPORTED"
                  and health_report.get("http_health_reported") is True
                  and health_report.get("expected_commit_verified") is False
                  and health_report.get("customer_outcome_certified") is False)
    # A service-specific anonymous health endpoint does not authenticate a
    # deployed commit, prove application behavior, or satisfy a customer's tests.
    # Even if both upstream reports match, actual endpoint/version, budget,
    # permissions and customer acceptance remain unverified.
    issues.extend(["independent-service-health-unverified",
                   "deployment-cost-unverified",
                   "customer-acceptance-unverified"])
    result = {
        "schema": "privi-done-provider-correlation-v1",
        "repository": repository,
        "commit_sha": commit_sha,
        "render_service_id": service_id,
        "github_checks_reported_success": bool(gh),
        "render_live_commit_reported": bool(rd),
        "privi_one_sandbox_health_reported": health,
        "status": "PROVIDER_REPORTS_MATCH_OUTCOME_PENDING"
            if gh and rd else "PROVIDER_EVIDENCE_FAILED",
        "issues": issues,
        "completed": False,
        "invoiceable_as_verified_outcome": False,
        "human_review_required": True,
        "verified_customer_outcome": False,
    }
    result["report_sha256"] = hashlib.sha256(
        b"PRIVI-DONE-PROVIDER-REPORT-v1\x00" + _canon(result)).hexdigest()
    return result


def render_customer_markdown(report):
    """Produce human-readable progress, never an unearned 'DONE' certificate."""
    if (not isinstance(report, dict)
            or report.get("schema") != "privi-done-provider-correlation-v1"
            or report.get("completed") is not False
            or report.get("invoiceable_as_verified_outcome") is not False
            or report.get("verified_customer_outcome") is not False
            or not isinstance(report.get("issues"), list)
            or not isinstance(report.get("report_sha256"), str)
            or len(report["report_sha256"]) != 64):
        raise ValueError("not an independently certified DONE report")
    return "\n".join([
        "# Privi DONE — Deployment evidence review",
        "",
        "**Status:** " + str(report["status"]).replace("_", " "),
        "",
        "**Repository:** " + report["repository"],
        "**Commit:** \`" + report["commit_sha"] + "\`",
        "**Render service:** \`" + report["render_service_id"] + "\`",
        "**GitHub checks reported success:** " + ("Yes" if report["github_checks_reported_success"] else "No"),
        "**Render reports matching live commit:** " + ("Yes" if report["render_live_commit_reported"] else "No"),
        "**Privi ONE public sandbox health:** " + (
            "Not checked" if report.get("privi_one_sandbox_health_reported") is None else
            "Observed (not commit-specific)" if report["privi_one_sandbox_health_reported"] else
            "Not verified"),
        "",
        "**Not certified as completed. No independently checked endpoint health, customer acceptance or cost.**",
        "",
        "## What is still missing",
        *("- " + item.replace("-", " ") for item in report["issues"]),
        "",
        "**Report checksum (not a signature):** \`" + report["report_sha256"] + "\`",
        "",
        "This is a provider-status summary, not payment authorization, execution proof, or a customer acceptance certificate.",
        ""
    ])
