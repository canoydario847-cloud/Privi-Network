"""A customer-scoped, non-billing acceptance *review* for Privi DONE.

Contract is agreed BEFORE a run; report is evidence for review only. Neither
self-reported HTTP responses nor an entered customer name can express actual
customer approval. This module cannot certify, pay, invoice or execute tasks.
"""
import hashlib
import json
import re

SHA = re.compile(r"^[a-f0-9]{40}$")
ID = re.compile(r"^[A-Z0-9][A-Z0-9_-]{5,63}$")
CHECK_NAMES = (
    "sandbox_health", "version_self_report",
    "local_journal_audit_reported", "unsigned_checkpoint_correlates",
)
EXPECTED_ORIGIN = "https://privi-done-version-preview.onrender.com"


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")).hexdigest()


def assess_pilot_scope(scope, observation):
    """Check explicit criteria against a separately fetched observation.

    The caller MUST fetch observation directly from the fixed allowed service;
    never let a customer-supplied report JSON count as independently observed.
    """
    if not isinstance(scope, dict) or set(scope) != {
        "pilot_id", "scope_owner", "repository", "service_id",
        "expected_commit", "required_observations", "acceptance_policy",
    }:
        raise ValueError("invalid pilot scope schema")
    if (not isinstance(scope["pilot_id"], str)
            or not ID.fullmatch(scope["pilot_id"])
            or not isinstance(scope["scope_owner"], str)
            or not 2 <= len(scope["scope_owner"]) <= 120
            or any(c in scope["scope_owner"] for c in ("\n", "\r", "<", ">"))
            or scope["repository"] != "canoydario847-cloud/Privi-Network"
            or scope["service_id"] != "srv-dbvlkvt9el5s73a5dv80"
            or not isinstance(scope["expected_commit"], str)
            or not SHA.fullmatch(scope["expected_commit"])
            or not isinstance(scope["required_observations"], list)
            or not scope["required_observations"]
            or len(set(scope["required_observations"])) != len(scope["required_observations"])
            or any(not isinstance(x, str) or x not in CHECK_NAMES
                   for x in scope["required_observations"])
            or scope["acceptance_policy"] != "HUMAN_SIGNOFF_REQUIRED_NO_AUTOBILL"):
        raise ValueError("invalid or unsupported pilot scope")
    if not isinstance(observation, dict):
        raise ValueError("observation must be a dictionary")
    fields = observation.get("observations")
    matching = (observation.get("schema") == "privi-done-functional-readonly-v1"
                and observation.get("origin") == EXPECTED_ORIGIN
                and observation.get("expected_sha") == scope["expected_commit"]
                and isinstance(fields, dict)
                and set(fields) == set(CHECK_NAMES)
                and all(type(value) is bool for value in fields.values())
                and observation.get("execution_attested") is False
                and observation.get("journal_crypto_proof") is False
                and observation.get("cost_verified") is False
                and observation.get("customer_accepted") is False
                and observation.get("invoiceable") is False
                and observation.get("result") in (
                    "SANDBOX_READONLY_BEHAVIOR_OBSERVED_UNCERTIFIED",
                    "FUNCTIONAL_EVIDENCE_INCOMPLETE"))
    passing = bool(matching and all(fields[name] for name in scope["required_observations"]))
    result = {
        "schema": "privi-done-pilot-review-v1",
        "pilot_id": scope["pilot_id"],
        "scope_owner": scope["scope_owner"],
        "repository": scope["repository"],
        "service_id": scope["service_id"],
        "expected_commit": scope["expected_commit"],
        "scope_sha256": _digest(scope),
        "required_observations": list(scope["required_observations"]),
        "criteria_observed": passing,
        "result": "CRITERIA_OBSERVED_AWAITING_OWNER_REVIEW"
            if passing else "CRITERIA_INCOMPLETE_OR_UNTRUSTED",
        "proof_limitations": [
            "no-independent-code-execution-attestation",
            "no-independent-journal-cryptographic-proof",
            "costs-and-uptime-not-verified",
            "owner-acceptance-not-received",
        ],
        "owner_accepted": False,
        "outcome_certified": False,
        "invoiceable": False,
    }
    result["checksum_sha256_not_signature"] = _digest(result)
    return result


def to_markdown(report):
    if (not isinstance(report, dict)
            or report.get("schema") != "privi-done-pilot-review-v1"
            or report.get("owner_accepted") is not False
            or report.get("outcome_certified") is not False
            or report.get("invoiceable") is not False
            or not isinstance(report.get("proof_limitations"), list)):
        raise ValueError("not a noncertifying pilot report")
    lines = [
        "# Privi DONE | Pilot acceptance review",
        "",
        "**Made by Dario Canoy**",
        "",
        "**Status:** " + report["result"].replace("_", " "),
        "",
        "**Pilot ID:** `" + report["pilot_id"] + "`",
        "**Scope owner:** " + report["scope_owner"],
        "**Repository:** `" + report["repository"] + "`",
        "**Service ID:** `" + report["service_id"] + "`",
        "**Pinned commit:** `" + report["expected_commit"] + "`",
        "**Pre-agreed scope checksum:** `" + report["scope_sha256"] + "`",
        "",
        "## Agreed observations",
    ]
    lines += ["- " + x.replace("_", " ") for x in report["required_observations"]]
    lines += [
        "",
        "**All requested conditions observed:** " + (
            "Yes (not a completion certificate)" if report["criteria_observed"]
            else "No"),
        "",
        "## Evidence still required",
    ]
    lines += ["- " + x.replace("-", " ") for x in report["proof_limitations"]]
    lines += [
        "",
        "**No customer signoff has been received. No invoice or settlement authorized.**",
        "",
        "**Report checksum (not a signature):** `" +
            report["checksum_sha256_not_signature"] + "`",
        "",
        "This record shows provider and sandbox behavior for human review only.",
        "",
    ]
    return "\n".join(lines)
