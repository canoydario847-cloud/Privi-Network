#!/usr/bin/env python3
"""Read-only Render validator candidate audit. NEVER deploy or approve PRVI mainnet.

This validates a NO-SECRETS manifest against optional exported Render list_services
JSON. No Render credentials, network calls, key creation, paid resources, or
financial release actions are performed. Provider metadata is not signer proof.
"""
import argparse
import json
import re
from pathlib import Path

SLOTS = {f"privi-owner-val-{i:02d}" for i in range(1, 5)}
NAME = re.compile(r"^privi-pop-validator-0[1-4]$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REGIONS = {"oregon", "ohio", "virginia", "frankfurt", "singapore"}
UNASSIGNED = "UNASSIGNED"
FIELDS = {
    "schema_version", "purpose", "operator", "provider", "workspace_id",
    "financial_launch_enabled", "production_ready", "release_sha256",
    "genesis_sha256", "cross_region_p2p_security_review",
    "failure_domain_review", "validators",
}
NODE_FIELDS = {
    "id", "service_name", "service_id", "region", "fault_domain",
    "consensus_pubkey_sha256", "signer_security_review", "disk_mount",
    "minimum_disk_gb", "manual_deploy", "instance_count", "expected_type",
}
SENSITIVE_KEY = re.compile(
    r"(?:private[_-]?key|mnemonic|secret|password|seed[_-]?phrase|"
    r"api[_-]?key|access[_-]?token|jwt|recovery[_-]?phrase)", re.I
)
SENSITIVE_VALUE = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----|sk-proj-[A-Za-z0-9_-]{15,}", re.I
)


class InvalidCandidate(ValueError):
    pass


def unique_json(items):
    result = {}
    for key, value in items:
        if key in result:
            raise InvalidCandidate(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    # No file-size-exhaustion or duplicate-key bypass in untrusted exports.
    file = Path(path)
    if file.stat().st_size > 4_000_000:
        raise InvalidCandidate("JSON input exceeds 4 MB safety limit")
    return json.loads(file.read_text(encoding="utf-8"), object_pairs_hook=unique_json)


def _has_secret_fields(item):
    if isinstance(item, dict):
        for key, value in item.items():
            if SENSITIVE_KEY.search(key) or _has_secret_fields(value):
                return True
    elif isinstance(item, list):
        return any(_has_secret_fields(value) for value in item)
    elif isinstance(item, str):
        return bool(SENSITIVE_VALUE.search(item))
    return False


def _fields(item, required, label, errors):
    if not isinstance(item, dict):
        errors.append(f"{label}: expected JSON object")
        return False
    extra, missing = set(item) - required, required - set(item)
    if extra:
        errors.append(f"{label}: unexpected keys: {', '.join(sorted(extra))}")
    if missing:
        errors.append(f"{label}: missing keys: {', '.join(sorted(missing))}")
    return True


def _assigned(value):
    return isinstance(value, str) and bool(value.strip()) and value != UNASSIGNED


def assess(manifest, services=None):
    """Return (structural errors, readiness blockers, observed service matches).

    A complete provider metadata match NEVER means this infrastructure is safe
    to start. Independent host/signer/genesis/release evidence is mandatory.
    """
    errors, blockers = [], []
    matches = 0
    if not _fields(manifest, FIELDS, "manifest", errors):
        return errors, ["manifest invalid"], matches
    if _has_secret_fields(manifest):
        errors.append("manifest: credential/secret data forbidden (value redacted)")
    constants = {
        "schema_version": 1,
        "purpose": "RENDER_PRODUCTION_VALIDATOR_CANDIDATE_NOT_DEPLOYED",
        "operator": "Privi World Corp",
        "provider": "render",
        "financial_launch_enabled": False,
        "production_ready": False,
    }
    for key, wanted in constants.items():
        if type(manifest.get(key)) is not type(wanted) or manifest.get(key) != wanted:
            errors.append(f"{key}: nonfinancial candidate marker is mandatory")
    workspace = manifest.get("workspace_id")
    if not _assigned(workspace):
        blockers.append("Render workspace identity not assigned")
    for key in ("release_sha256", "genesis_sha256"):
        value = manifest.get(key)
        if not _assigned(value):
            blockers.append(f"{key}: signed release/genesis digest absent")
        elif not SHA256.fullmatch(value):
            errors.append(f"{key}: expected lowercase SHA256 fingerprint")
    for key in ("failure_domain_review", "cross_region_p2p_security_review"):
        if not _assigned(manifest.get(key)):
            blockers.append(f"{key}: external attestation absent")
    candidates = manifest.get("validators")
    if not isinstance(candidates, list) or len(candidates) != 4:
        errors.append("exactly four Render private validator candidates required")
        return sorted(set(errors)), sorted(set(blockers)), matches

    service_map = {}
    if services is not None:
        if not isinstance(services, list):
            errors.append("Render observations must be a JSON list from list_services")
        else:
            for item in services:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    errors.append("malformed Render service record")
                    continue
                if item["id"] in service_map:
                    errors.append("duplicate Render provider service ID in observations")
                service_map[item["id"]] = item

    ids, names, service_ids, domains, pubkeys = set(), set(), set(), set(), set()
    observed_disk_ids = set()
    regions = set()
    for idx, node in enumerate(candidates):
        label = f"validator[{idx}]"
        if not _fields(node, NODE_FIELDS, label, errors):
            continue
        if node.get("id") not in SLOTS or node["id"] in ids:
            errors.append(f"{label}: validator ID is invalid or duplicated")
        else:
            ids.add(node["id"])
        ident = node.get("service_name")
        if not isinstance(ident, str) or not NAME.fullmatch(ident) or ident in names:
            errors.append(f"{label}: unsafe or duplicate Render service name")
        else:
            names.add(ident)
        if ident != f"privi-pop-validator-{idx+1:02d}":
            errors.append(f"{label}: service name/order mismatch")
        for key, seen in (
            ("service_id", service_ids),
            ("fault_domain", domains),
            ("consensus_pubkey_sha256", pubkeys),
        ):
            v = node.get(key)
            if not _assigned(v):
                blockers.append(f"{label}: {key} not verified")
            elif v in seen:
                errors.append(f"{label}: duplicate {key}")
            else:
                seen.add(v)
        if _assigned(node.get("consensus_pubkey_sha256")) and not SHA256.fullmatch(node["consensus_pubkey_sha256"]):
            errors.append(f"{label}: consensus public-key SHA256 malformed")
        region = node.get("region")
        if not _assigned(region):
            blockers.append(f"{label}: region not assigned")
        elif region not in REGIONS:
            errors.append(f"{label}: unsupported Render region")
        else:
            regions.add(region)
        if node.get("expected_type") != "private_service":
            errors.append(f"{label}: must require private_service (not web_service)")
        if node.get("manual_deploy") is not True:
            errors.append(f"{label}: production validator auto-deploy forbidden")
        if type(node.get("instance_count")) is not int or node.get("instance_count") != 1:
            errors.append(f"{label}: one service instance per signer required")
        if node.get("disk_mount") != "/data":
            errors.append(f"{label}: persistent disk mount must be /data")
        diskmin = node.get("minimum_disk_gb")
        if type(diskmin) is not int or diskmin < 10 or diskmin > 1024:
            errors.append(f"{label}: disk capacity threshold must be 10..1024 GB")
        if not _assigned(node.get("signer_security_review")):
            blockers.append(f"{label}: independent signer-security approval missing")
        service_id = node.get("service_id")
        if services is None or not _assigned(service_id):
            continue
        observed = service_map.get(service_id)
        if observed is None:
            blockers.append(f"{label}: assigned Render service ID not found in provider inventory")
            continue
        if _assigned(workspace) and observed.get("ownerId") != workspace:
            errors.append(f"{label}: Render service belongs to wrong workspace")
        if observed.get("name") != ident:
            errors.append(f"{label}: Render service name doesn't match candidate")
        if observed.get("type") != "private_service":
            errors.append(f"{label}: public/non-validator Render service type forbidden")
        if observed.get("autoDeploy") != "no":
            errors.append(f"{label}: Render provider auto-deploy must be disabled")
        if observed.get("suspended") not in ("not_suspended", None):
            blockers.append(f"{label}: Render service is suspended")
        details = observed.get("serviceDetails")
        if not isinstance(details, dict):
            errors.append(f"{label}: Render service details absent")
            continue
        if details.get("region") != region:
            errors.append(f"{label}: Render actual region mismatches approved candidate")
        if details.get("runtime") != "docker" and details.get("env") != "docker":
            errors.append(f"{label}: provider service must use reviewed Docker runtime")
        plan = details.get("plan")
        if not isinstance(plan, str) or plan in ("free", ""):
            errors.append(f"{label}: free/unknown Render compute plan forbidden")
        if type(details.get("numInstances")) is not int or details["numInstances"] != 1:
            errors.append(f"{label}: provider must run exactly one service instance")
        disk = details.get("disk")
        if not isinstance(disk, dict) or not _assigned(disk.get("id")):
            errors.append(f"{label}: attached persistent disk ID missing")
        else:
            if disk["id"] in observed_disk_ids:
                errors.append(f"{label}: two validators share a Render persistent disk ID")
            observed_disk_ids.add(disk["id"])
            if (disk.get("mountPath") != "/data" or
                type(disk.get("sizeGB")) not in (float, int) or
                type(diskmin) is not int or disk["sizeGB"] < diskmin):
                errors.append(f"{label}: persistent disk mount/capacity invalid")
        if details.get("url") and "onrender.com" in str(details["url"]):
            errors.append(f"{label}: public onrender.com endpoint forbidden on validator")
        matches += 1
    if ids != SLOTS:
        errors.append("four validator identities incomplete or duplicated")
    if len(regions) < 2:
        blockers.append("four signers lack cross-region failure-domain diversity")
    elif not _assigned(manifest.get("cross_region_p2p_security_review")):
        blockers.append("Render private networking is regional: cross-region secure P2P not approved")
    # Deliberately never assert 'production ready' from self-reported provider data.
    blockers.append("mandatory human security, signer, signed genesis/release and live quorum review")
    return sorted(set(errors)), sorted(set(blockers)), matches


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("--mode", choices=("draft", "observe", "production"), default="draft")
    p.add_argument("--render-services", type=Path,
                   help="read-only local JSON export from connected Render list_services")
    args = p.parse_args(argv)
    try:
        if args.mode == "observe" and args.render_services is None:
            raise InvalidCandidate("observe requires explicit Render provider JSON")
        candidate = read_json(args.manifest)
        services = read_json(args.render_services) if args.render_services else None
        errors, blockers, matches = assess(candidate, services)
    except (OSError, ValueError, TypeError) as exc:
        print("RENDER VALIDATOR AUDIT ERROR:", str(exc))
        return 2
    print(f"Render candidate structural_errors={len(errors)} "
          f"readiness_blockers={len(blockers)} provider_matches={matches}/4")
    for err in errors:
        print("ERROR:", err)
    for block in blockers:
        print("NO-GO:", block)
    print("FINANCIAL MAINNET: NOT LIVE; REAL PRVI ISSUANCE: NOT AUTHORIZED")
    if errors:
        return 2
    if args.mode == "draft":
        print("NONLIVE DRAFT STRUCTURE ACCEPTED; readiness NOT verified")
        return 0
    print("NO-GO: provider metadata alone cannot certify validator custody, "
          "PoP consensus safety or signed mainnet launch")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
