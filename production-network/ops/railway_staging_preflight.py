#!/usr/bin/env python3
"""Fail-closed assessment of the seven-validator Railway staging snapshot.

Data comes from Railway read-only provider observations; this program has NO
Railway credentials, network access, signing authority or deployment actions.
"Online" means a running service, NOT block finality or consensus identity.
"""
import argparse
import json
import re
from pathlib import Path

EXPECTED = {f"privi-validator-{i}" for i in range(7)} | {"privi-bootstrap"}
REQUIRED = {"schema_version", "observed_on", "source", "provider",
            "project_id", "project_name", "environment", "network_class",
            "repository", "branch", "release_sha256", "genesis_sha256",
            "production_approval", "services"}
SERVICE_FIELDS = {"name", "kind", "region", "state", "deployment_status", "volume_id"}
SECRET_NAMES = re.compile(r"(mnemonic|secret|password|private.?key|api.?key|seed.?phrase|recovery.?phrase|access.?token)", re.I)
PROHIBITED_VALUES = re.compile(r"sk-proj-[A-Za-z0-9_-]{15,}|-----BEGIN [^-]*PRIVATE KEY-----", re.I)


class ManifestError(ValueError):
    pass


def reject_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ManifestError(f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def secrets_guard(value, path="root"):
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_NAMES.search(key):
                raise ManifestError(f"{path}: sensitive field name forbidden")
            secrets_guard(item, path + "." + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            secrets_guard(item, path + f"[{index}]")
    elif isinstance(value, str) and PROHIBITED_VALUES.search(value):
        raise ManifestError(f"{path}: credential material forbidden")


def assess(snapshot):
    """Return (errors, launch_blockers); never interprets TEST as PRVI."""
    if not isinstance(snapshot, dict):
        return ["snapshot must be object"], ["production readiness unverified"]
    secrets_guard(snapshot)
    errors = []
    blocks = []
    if set(snapshot) != REQUIRED:
        errors.append("snapshot schema keys changed")
    expected = {
        "schema_version": 1,
        "provider": "Railway",
        "project_id": "fb95bfa1-d2e5-41c6-bab6-cc7dee3f113b",
        "environment": "staging",
        "network_class": "UPSTREAM_TEST_NOT_NATIVE_PRVI",
        "repository": "canoydario847-cloud/Privi-Network",
        "branch": "build/privi-seven-validators-20261016",
        "release_sha256": "UNVERIFIED",
        "genesis_sha256": "UNVERIFIED",
        "production_approval": "NONE",
    }
    for key, expected_value in expected.items():
        if type(snapshot.get(key)) is not type(expected_value) or snapshot.get(key) != expected_value:
            errors.append(f"{key}: unreviewed/unsafe staging identity")
    if not isinstance(snapshot.get("source"), str) or "read-only" not in snapshot["source"]:
        errors.append("provider source and read-only scope not recorded")
    if not isinstance(snapshot.get("observed_on"), str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", snapshot["observed_on"]
    ):
        errors.append("observation date missing or invalid")
    items = snapshot.get("services")
    if not isinstance(items, list) or len(items) != 8:
        return errors + ["expected seven staged validator services and bootstrap"], ["unverified validator hosts"]
    seen, volumes, regions = set(), set(), set()
    for row in items:
        if not isinstance(row, dict) or set(row) != SERVICE_FIELDS:
            errors.append("unexpected staged service schema")
            continue
        name = row["name"]
        if not isinstance(name, str) or name not in EXPECTED or name in seen:
            errors.append("duplicate or unexpected service")
            continue
        seen.add(name)
        if row["kind"] != ("bootstrap" if name == "privi-bootstrap" else "validator"):
            errors.append("wrong service classification")
        if row["state"] != "online" or row["deployment_status"] != "SUCCESS":
            errors.append("staging service not observed healthy at snapshot")
        region = row["region"]
        if not isinstance(region, str) or not re.fullmatch(r"[a-z0-9-]{2,25}", region):
            errors.append("invalid observed region")
        else:
            regions.add(region)
        volume = row["volume_id"]
        if not isinstance(volume, str) or not re.fullmatch(r"[0-9a-f-]{36}", volume) or volume in volumes:
            errors.append("missing or duplicate provider volume")
        else:
            volumes.add(volume)
    if seen != EXPECTED:
        errors.append("staged validator/bootstrap names incomplete")
    # A single fault region is acceptable for valueless staging; it is NOT
    # independent fault-domain evidence for a permissioned financial mainnet.
    if regions != {"iad"}:
        errors.append("observed staging region layout drift requires fresh provider evidence")
    blocks.extend([
        "upstream disposable TEST chain rather than custom native PRVI financial binary",
        "only one observed Railway geographic region/fault domain",
        "no four-host independently verified production signer or key attestations",
        "no signed and independently reviewed financial genesis/release hashes",
        "no approved independent financial security assessment",
        "no authenticated live P2P consensus/RPC identity proof for all staged services",
    ])
    return sorted(set(errors)), blocks


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("snapshot", type=Path)
    p.add_argument("--mode", choices=("staging", "production"), default="staging")
    args = p.parse_args()
    try:
        raw = args.snapshot.read_text(encoding="utf-8")
        if len(raw) > 65536:
            raise ManifestError("oversized staging observation")
        data = json.loads(raw, object_pairs_hook=reject_duplicate_keys)
        errors, blocks = assess(data)
    except (OSError, UnicodeError, ValueError) as exc:
        print("REJECTED: malformed or sensitive staging observation:", type(exc).__name__)
        return 2
    for error in errors:
        print("STAGING INTEGRITY ERROR:", error)
    for block in blocks:
        print("FINANCIAL MAINNET BLOCKED:", block)
    if errors:
        return 2
    if args.mode == "production":
        print("NO-GO: Railway staging provider status never certifies financial PRVI mainnet")
        return 3
    print("PASS: eight Railway services observed online with distinct volumes; TEST only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
