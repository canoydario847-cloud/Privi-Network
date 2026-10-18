#!/usr/bin/env python3
"""Fail-closed policy audit for four Privi World Corp-operated validators.

This validates a NO-SECRETS candidate inventory. It does NOT provision
validators, sign a genesis, contact hosts or activate a financial network.
"""
import argparse
import ipaddress
import json
import re
from pathlib import Path

OWNER = "Privi World Corp"
IDS = {f"privi-owner-val-{i:02d}" for i in range(1, 5)}
UNASSIGNED = "UNASSIGNED"
HEX64 = re.compile(r"^[a-fA-F0-9]{64}$")
NODEID = re.compile(r"^[a-fA-F0-9]{40}$")
SECRET_FIELD = re.compile(r"(mnemonic|password|secret|private[_-]?key|seed[_-]?phrase|api[_-]?key|access[_-]?token|jwt|recovery[_-]?phrase)", re.I)
SECRET_VALUE = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----|sk-proj-[a-zA-Z0-9_-]{15,}", re.I)
EXPECTED_KEYS = {
    "schema_version", "network", "operator", "governance_model",
    "independent_operator_count", "financial_launch_enabled",
    "production_ready", "release_sha256", "genesis_sha256",
    "security_review_reference", "final_owner_approval_reference",
    "testnet_evidence_reference", "validators",
}
NODE_KEYS = {
    "id", "operator", "host_id", "fault_domain", "region",
    "private_p2p_ip", "node_id", "consensus_pubkey_sha256",
    "signer_type", "signer_attestation", "sentry_reference",
    "rpc_listen", "metrics_listen", "key_storage_attestation",
    "voting_power_percent",
}

class InvalidInventory(ValueError):
    pass

def no_duplicate_keys(items):
    result = {}
    for k, v in items:
        if k in result:
            raise InvalidInventory(f"duplicate JSON key: {k}")
        result[k] = v
    return result

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)

def assess(data):
    """Return (structural_errors, readiness_blockers) without exposing secrets."""
    errors, blocks = [], []
    if not isinstance(data, dict):
        return ["manifest must be a JSON object"], ["not ready"]
    def report_unknown(obj, expected, label):
        extra = set(obj) - expected
        missing = expected - set(obj)
        if extra:
            errors.append(f"{label}: unexpected keys: {', '.join(sorted(extra))}")
        if missing:
            errors.append(f"{label}: missing keys: {', '.join(sorted(missing))}")
    def inspect_secrets(value, place="inventory"):
        if isinstance(value, dict):
            for k, v in value.items():
                if SECRET_FIELD.search(k) and k not in {"consensus_pubkey_sha256"}:
                    errors.append(f"{place}: forbidden sensitive field name {k!r}")
                inspect_secrets(v, f"{place}.{k}")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                inspect_secrets(item, f"{place}[{i}]")
        elif isinstance(value, str) and SECRET_VALUE.search(value):
            errors.append(f"{place}: potentially sensitive credential included; value intentionally redacted")
    inspect_secrets(data)
    report_unknown(data, EXPECTED_KEYS, "manifest")
    for key, value in {
        "schema_version": 1, "operator": OWNER,
        "governance_model": "single-operator-permissioned",
        "independent_operator_count": 1, "financial_launch_enabled": False,
        "production_ready": False,
    }.items():
        if type(data.get(key)) is not type(value) or data.get(key) != value:
            errors.append(f"{key} must be {value!r} for a non-live owner-operated candidate")
    network = data.get("network")
    if not isinstance(network, str) or not network.startswith("privi-") or "NOT_DEPLOYED" not in network:
        errors.append("network must remain clearly identified as a non-deployed candidate")
    nodes = data.get("validators")
    if not isinstance(nodes, list) or len(nodes) != 4:
        errors.append("exactly four validator records required")
        return errors, blocks
    ids, hosts, domains, ips, nodeids, fingerprints, sentries = set(), set(), set(), set(), set(), set(), set()
    def unique(label, item, seen, node):
        if item in ("", None, UNASSIGNED):
            blocks.append(f"{node}: {label} is not assigned")
        elif not isinstance(item, str):
            errors.append(f"{node}: {label} must be a string")
        elif item in seen:
            errors.append(f"{node}: duplicated {label}")
        else:
            seen.add(item)
    total_power = 0
    for idx, node in enumerate(nodes):
        name = f"validator[{idx}]"
        if not isinstance(node, dict):
            errors.append(f"{name}: expected object")
            continue
        report_unknown(node, NODE_KEYS, name)
        ident = node.get("id")
        if ident not in IDS:
            errors.append(f"{name}: invalid validator identity")
        unique("validator id",ident,ids,name)
        if node.get("operator") != OWNER:
            errors.append(f"{name}: validator must be owned/operated by {OWNER}")
        for key, seen in [
            ("host_id",hosts), ("fault_domain",domains),
            ("private_p2p_ip",ips), ("node_id",nodeids),
            ("consensus_pubkey_sha256",fingerprints),
            ("sentry_reference",sentries),
        ]:
            unique(key,node.get(key),seen,name)
        ip = node.get("private_p2p_ip")
        if ip not in (None,"",UNASSIGNED):
            try:
                parsed = ipaddress.ip_address(ip)
                if not parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_multicast:
                    errors.append(f"{name}: P2P IP must be a routable, private, non-loopback address")
            except (ValueError,TypeError):
                errors.append(f"{name}: P2P IP must be a valid private IP")
        for key, pattern in [
            ("consensus_pubkey_sha256",HEX64), ("node_id",NODEID),
        ]:
            v=node.get(key)
            if v not in (None,"",UNASSIGNED) and (not isinstance(v,str) or not pattern.fullmatch(v)):
                errors.append(f"{name}: invalid public {key} fingerprint")
        for key in ("region","signer_attestation","key_storage_attestation"):
            v = node.get(key)
            if not isinstance(v,str):
                errors.append(f"{name}: {key} must be text")
            elif v.strip() in ("",UNASSIGNED):
                blocks.append(f"{name}: {key} evidence missing")
        signer=node.get("signer_type")
        if signer not in ("remote-signer","HSM-with-reviewed-CometBFT-adapter","UNASSIGNED"):
            errors.append(f"{name}: unsupported/unsafe signer type")
        if signer==UNASSIGNED:
            blocks.append(f"{name}: signer type not selected")
        for key in ("rpc_listen","metrics_listen"):
            if node.get(key) not in ("127.0.0.1","::1"):
                errors.append(f"{name}: {key} must be loopback-only")
        power=node.get("voting_power_percent")
        if type(power) is not int or power!=25:
            errors.append(f"{name}: voting power must equal 25 percent")
        else:
            total_power+=power
    if ids!=IDS:
        errors.append("validator IDs must be exactly privi-owner-val-01 through 04")
    if total_power!=100:
        errors.append("voting power must sum to exactly 100 percent")
    for key in ("release_sha256","genesis_sha256"):
        v = data.get(key)
        if v in (None,"",UNASSIGNED):
            blocks.append(f"release evidence missing: {key}")
        elif not isinstance(v,str) or not HEX64.fullmatch(v):
            errors.append(f"{key} must be a SHA-256 hex digest")
    for key in ("security_review_reference","final_owner_approval_reference","testnet_evidence_reference"):
        v=data.get(key)
        if not isinstance(v,str):
            errors.append(f"{key} must be a textual reference")
        elif v.strip() in ("",UNASSIGNED):
            blocks.append(f"release evidence missing: {key}")
    return sorted(set(errors)),sorted(set(blocks))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    parser.add_argument("--mode",choices=("draft","preflight"),default="draft")
    args=parser.parse_args()
    try:
        data=load(args.manifest)
        errors, blockers=assess(data)
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print("OWNER VALIDATOR INVENTORY REJECTED:",str(exc))
        return 2
    print(f"Privi four-owner-validator inventory: structural_errors={len(errors)} readiness_blockers={len(blockers)}")
    for issue in errors:
        print("ERROR:",issue)
    for issue in blockers:
        print("NOT READY:",issue)
    print("Independent validator operators: 1 (centralized owner, four proposed nodes)")
    print("Financial PRVI mainnet: NOT ACTIVE")
    if errors:
        return 2
    if args.mode=="preflight":
        # A structurally complete manifest cannot self-certify a production
        # release or represent an external audit. This preflight is ALWAYS
        # NO-GO until separately validated, signed evidence is reviewed.
        print("NO-GO: independent security/release review and real host attestations required")
        return 3
    print("DRAFT ACCEPTED; financial launch still blocked")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
