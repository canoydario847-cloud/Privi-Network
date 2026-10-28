#!/usr/bin/env python3
"""Fail-closed offline Privi mainnet evidence gate. No keys, chain writes or network calls."""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

REQUIRED = (
    "custom_chain_audit",
    "pop_consensus_spec_and_review",
    "genesis_supply_and_vesting_review",
    "validator_independence",
    "genesis_signatures",
    "key_custody_and_double_sign_prevention",
    "public_testnet_consensus_and_evm_tests",
    "rpc_monitoring_and_incident_drill",
    "security_audit",
    "legal_and_financial_launch_approval",
)

def valid_evidence_url(value):
    """Reject malformed and example-only links without fetching private evidence."""
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        url = urlsplit(value)
        hostname = url.hostname
        _ = url.port  # force invalid port syntax validation
    except ValueError:
        return False
    if (url.scheme != "https" or not hostname or url.username is not None
            or url.password is not None or url.fragment or not url.path.strip("/")):
        return False
    host = hostname.lower().rstrip(".")
    if (host == "localhost" or host.endswith(".localhost")
            or host in {"example.com", "example.org", "example.net"}
            or host.endswith((".example", ".test", ".invalid", ".local"))):
        return False
    return True

def check(document):
    if not isinstance(document, dict):
        return ["evidence must be a JSON object"]
    if document.get("network") != "privi-native-mainnet":
        return ["network must be privi-native-mainnet"]
    if document.get("asset") != "PRVI":
        return ["asset must be PRVI"]
    errors = []
    for gate in REQUIRED:
        item = document.get("gates", {}).get(gate) if isinstance(document.get("gates"), dict) else None
        if not isinstance(item, dict) or item.get("status") != "verified":
            errors.append(f"{gate}: not verified")
        elif not valid_evidence_url(item.get("evidence_url")):
            errors.append(f"{gate}: invalid HTTPS evidence URL (non-example report link required)")
        elif not isinstance(item.get("reviewer"), str) or not item["reviewer"].strip():
            errors.append(f"{gate}: missing reviewer")
    return errors

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"BLOCKED: cannot load evidence: {exc}")
        return 2
    errors = check(document)
    if errors:
        print("NO-GO: native financial mainnet launch is blocked")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Evidence checklist complete; independent live verification and explicit deployment authorization still required.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
