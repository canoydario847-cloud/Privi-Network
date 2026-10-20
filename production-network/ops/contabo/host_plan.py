#!/usr/bin/env python3
"""Offline validation of a four-host Contabo valueless staging inventory.

No API calls, billing, key generation, remote SSH, genesis or node activation.
A passing draft is not evidence of cloud tenancy or host isolation.
"""
import argparse
import ipaddress
import json
import re
from pathlib import Path

IDS = {f"privi-owner-val-{i:02d}" for i in range(1, 5)}
REQUIRED = {"schema_version", "provider", "purpose", "operator", "financial_mainnet_enabled",
            "auto_provision_enabled", "real_prvi_issuance_enabled", "nodes"}
NODE = {"id", "instance_id", "region", "fault_domain", "public_ipv4",
        "private_overlay_ipv4", "admin_ssh_public_key_fingerprint", "rpc_bind", "metrics_bind"}
SHA256_SSH = re.compile(r"^SHA256:[a-zA-Z0-9+/]{43}$")
SECRETS = re.compile(r"(private.?key|mnemonic|seed.?phrase|password|api.?token|api.?key|secret|access.?token|bearer)", re.I)
UNASSIGNED = "UNASSIGNED"
RFC1918 = tuple(ipaddress.ip_network(net) for net in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"
))

def pairs_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key (name redacted)")
        result[key] = value
    return result

def inspect(plan):
    """Return (structural_errors, evidence_blockers)."""
    errs, blocks = [], []
    def fail_secret(value, path="root"):
        if isinstance(value, dict):
            for key, item in value.items():
                if SECRETS.search(key):
                    errs.append(f"{path}: forbidden credential-like field")
                fail_secret(item, f"{path}.{key}")
        elif isinstance(value, list):
            for item in value:
                fail_secret(item, path + "[]")
        elif isinstance(value, str) and ("-----BEGIN PRIVATE KEY-----" in value or "sk-proj-" in value):
            errs.append(f"{path}: forbidden credential-like value")
    fail_secret(plan)
    if not isinstance(plan, dict):
        return ["inventory must be JSON object"], []
    if set(plan) != REQUIRED:
        errs.append(f"inventory keys differ: expected {sorted(REQUIRED)}")
    expected = {"schema_version": 1, "provider": "contabo", "purpose": "valueless-multi-host-testnet",
                "operator": "Privi World Corp", "financial_mainnet_enabled": False,
                "auto_provision_enabled": False, "real_prvi_issuance_enabled": False}
    for key, target in expected.items():
        if type(plan.get(key)) is not type(target) or plan.get(key) != target:
            errs.append(f"{key} must equal {target!r}")
    nodes = plan.get("nodes")
    if not isinstance(nodes, list) or len(nodes) != 4:
        return errs + ["exactly four proposed hosts required"], blocks
    seen = {key: set() for key in ("id", "instance_id", "fault_domain", "public_ipv4",
                                     "private_overlay_ipv4", "admin_ssh_public_key_fingerprint")}
    for ix, node in enumerate(nodes):
        prefix = f"node[{ix}]"
        if not isinstance(node, dict):
            errs.append(prefix + " must be object")
            continue
        if set(node) != NODE:
            errs.append(prefix + ": missing/extra host fields")
        ident = node.get("id")
        if not isinstance(ident, str) or ident not in IDS:
            errs.append(prefix + ": invalid ID")
        for key in seen:
            value = node.get(key)
            if not isinstance(value, str) or not value.strip():
                errs.append(prefix + f": {key} must be nonempty text")
            elif value == UNASSIGNED:
                blocks.append(prefix + f": {key} not supplied")
            elif value in seen[key]:
                errs.append(prefix + f": duplicate {key}")
            else:
                seen[key].add(value)
        region = node.get("region")
        if not isinstance(region, str) or not region.strip():
            errs.append(prefix + ": region must be text")
        elif region == UNASSIGNED:
            blocks.append(prefix + ": cloud region unassigned")
        fpr = node.get("admin_ssh_public_key_fingerprint")
        if fpr != UNASSIGNED and (not isinstance(fpr, str) or not SHA256_SSH.fullmatch(fpr)):
            errs.append(prefix + ": malformed SSH public key fingerprint")
        for key, require_private in (("public_ipv4", False), ("private_overlay_ipv4", True)):
            value = node.get(key)
            if value == UNASSIGNED:
                continue
            try:
                address = ipaddress.IPv4Address(value)
            except (ValueError, TypeError):
                errs.append(prefix + f": {key} must be an IPv4 address")
                continue
            if require_private:
                if not any(address in network for network in RFC1918):
                    errs.append(prefix + ": overlay IP must be RFC1918, nonloopback")
            elif not address.is_global:
                errs.append(prefix + ": public IPv4 must be globally routable")
        for key in ("rpc_bind", "metrics_bind"):
            if node.get(key) != "127.0.0.1":
                errs.append(prefix + f": {key} must bind loopback only")
    valid_ids = {node["id"] for node in nodes if isinstance(node, dict) and isinstance(node.get("id"), str)}
    if valid_ids != IDS:
        errs.append("node IDs must be exactly 01 through 04")
    return sorted(set(errs)), sorted(set(blocks))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--mode", choices=("draft", "preflight"), default="draft")
    args = parser.parse_args()
    try:
        obj = json.loads(args.inventory.read_text(encoding="utf-8"), object_pairs_hook=pairs_unique)
        errors, blockers = inspect(obj)
    except (OSError, ValueError) as exc:
        print("REJECTED:", exc)
        return 2
    for item in errors:
        print("ERROR:", item)
    for item in blockers:
        print("MISSING EVIDENCE:", item)
    if errors:
        print("REJECTED: invalid host inventory")
        return 2
    if args.mode == "preflight":
        print("NO-GO: an offline manifest cannot attest real hosts, signed binaries, keys or isolation")
        return 3
    print("DRAFT VALIDATED: four proposed Contabo hosts; no cloud resources created")
    print("FINANCIAL PRVI MAINNET: NOT DEPLOYED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
