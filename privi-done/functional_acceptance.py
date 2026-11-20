"""Privi DONE: read-only functional acceptance observation for a pinned preview.

This exercises real GET behavior of a *single fixed Privi-owned sandbox*:
health, deployed version self-report, local journal audit and checkpoint.
It NEVER generates sessions, writes receipts, triggers deployment, charges
a user, accesses wallets or fetches caller-controlled URLs.

Passing means the sandbox *reported* those expected behaviors. It is not
independent proof of journal integrity, code execution or customer acceptance.
"""
import hashlib
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

ORIGIN = "https://privi-done-version-preview.onrender.com"
SHA = re.compile(r"^[a-f0-9]{40}$")
HASH = re.compile(r"^[a-f0-9]{64}$")
ENDPOINTS = ("/health", "/api/version", "/api/audit", "/api/checkpoint")


class ReadOnlyProbeUnavailable(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get(path):
    """Fixed-origin GET; no redirects; no custom path, user inputs or auth."""
    if path not in ENDPOINTS:
        raise ReadOnlyProbeUnavailable("not an allowed sandbox GET")
    target = ORIGIN + path
    req = Request(target, method="GET", headers={
        "Accept": "application/json",
        "User-Agent": "Privi-DONE-readonly-functional/0.1",
    })
    try:
        with build_opener(NoRedirect()).open(req, timeout=75) as response:
            if response.status != 200 or response.geturl() != target:
                raise ReadOnlyProbeUnavailable("unexpected HTTP response")
            raw = response.read(8193)
            if len(raw) > 8192:
                raise ReadOnlyProbeUnavailable("response too large")
            return json.loads(raw)
    except (HTTPError, URLError, OSError, TimeoutError, UnicodeError,
            ValueError, TypeError) as exc:
        raise ReadOnlyProbeUnavailable("sandbox functional GET unavailable") from exc


def observe(expected_sha, *, get=None):
    """Return JSON-safe partial evidence with no secret or raw journal data."""
    if not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha):
        raise ValueError("pinned full Git commit SHA required")
    reader = _get if get is None else get  # test-only injection
    observations = {}
    for path in ENDPOINTS:
        try:
            value = reader(path)
            if not isinstance(value, dict):
                raise ReadOnlyProbeUnavailable("unexpected response object")
            observations[path] = value
        except (ReadOnlyProbeUnavailable, OSError, TimeoutError,
                ValueError, TypeError):
            observations[path] = None
    health = observations["/health"]
    version = observations["/api/version"]
    audit = observations["/api/audit"]
    checkpoint = observations["/api/checkpoint"]
    checks = {
        "sandbox_health": bool(
            isinstance(health, dict)
            and health.get("ok") is True
            and health.get("service") == "privi-one-demo"
            and health.get("mode") == "PRELAUNCH_SIMULATION"),
        "version_self_report": bool(
            isinstance(version, dict)
            and set(version) == {"service", "mode", "version_source",
                                 "self_reported_commit", "independently_attested"}
            and version.get("service") == "privi-one-demo"
            and version.get("mode") == "PRELAUNCH_SIMULATION"
            and version.get("self_reported_commit") == expected_sha
            and version.get("version_source") == "RENDER_GIT_COMMIT_ENV"
            and version.get("independently_attested") is False),
        "local_journal_audit_reported": bool(
            isinstance(audit, dict)
            and set(audit) == {"valid", "entries_checked", "head", "scope"}
            and audit.get("valid") is True
            and type(audit.get("entries_checked")) is int
            and 0 <= audit["entries_checked"] <= 10_000_000
            and isinstance(audit.get("head"), str)
            and HASH.fullmatch(audit["head"])
            and audit.get("scope") == "LOCAL_SQLITE_TAMPER_EVIDENCE_NOT_EXTERNAL_PROOF"),
        "unsigned_checkpoint_correlates": False
    }
    if checks["local_journal_audit_reported"]:
        checks["unsigned_checkpoint_correlates"] = bool(
            isinstance(checkpoint, dict)
            and set(checkpoint) == {"schema", "sequence", "head", "mode"}
            and checkpoint.get("schema") == "privi-one-external-checkpoint-v1"
            and checkpoint.get("mode") == "LOCAL_SANDBOX_UNSIGNED_CHECKPOINT"
            and type(checkpoint.get("sequence")) is int
            and checkpoint["sequence"] == audit["entries_checked"]
            and checkpoint.get("head") == audit["head"]
        )
    report = {
        "schema": "privi-done-functional-readonly-v1",
        "origin": ORIGIN,
        "expected_sha": expected_sha,
        "observations": checks,
        "result": "SANDBOX_READONLY_BEHAVIOR_OBSERVED_UNCERTIFIED"
            if all(checks.values()) else "FUNCTIONAL_EVIDENCE_INCOMPLETE",
        "journal_crypto_proof": False,
        "execution_attested": False,
        "cost_verified": False,
        "customer_accepted": False,
        "invoiceable": False,
    }
    report["sha256_checksum_not_signature"] = hashlib.sha256(
        b"PRIVI-DONE-FUNCTIONAL-OBSERVATION-v1\x00" +
        json.dumps(report, sort_keys=True, separators=(",", ":"),
                   allow_nan=False).encode("ascii")
    ).hexdigest()
    return report
