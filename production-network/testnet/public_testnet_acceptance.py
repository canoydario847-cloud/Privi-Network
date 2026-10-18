#!/usr/bin/env python3
"""Read-only public TESTNET evidence verifier; never launches, signs or mints.

Results show agreement between RPC observers and an attested operator roster.
Claims of *independent ownership* must still be established outside this script.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from consensus_audit import audit as comet_audit, validator_set
from evm_smoke import RPC

HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
FORBIDDEN_KEYS = {"mnemonic", "private_key", "seed_phrase", "secret_key", "password"}

def https_host(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.query or parsed.fragment or parsed.port == 0:
            return None
        return parsed.hostname.lower()
    except ValueError:
        return None

def secret_keys_found(value):
    if isinstance(value, dict):
        for key, val in value.items():
            if str(key).lower() in FORBIDDEN_KEYS or secret_keys_found(val):
                return True
    if isinstance(value, list):
        return any(secret_keys_found(x) for x in value)
    return False

def validate_manifest(manifest):
    errors = []
    def require(yes, message):
        if not yes:
            errors.append(message)

    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    require(not secret_keys_found(manifest), "secret/private-key field is forbidden")
    require(manifest.get("network_type") == "public_testnet", "network_type must be public_testnet")
    require(manifest.get("valueless_asset") is True, "TEST must be explicitly valueless")
    require(manifest.get("asset_symbol") == "TEST", "public-testnet asset must be TEST, never PRVI")
    require(manifest.get("bnb_priv_separate") is True, "BNB PRIV must remain separate")
    require(manifest.get("financial_mainnet_live") is False, "financial_mainnet_live must be false")
    cosmos = manifest.get("cosmos_chain_id")
    evm = manifest.get("evm_chain_id")
    require(isinstance(cosmos, str) and len(cosmos.strip()) >= 4 and cosmos != "local-4221",
            "reviewed non-local public-testnet Cosmos chain ID required")
    require(type(evm) is int and evm > 0 and evm not in (1, 56, 97, 4221, 262144),
            "reviewed non-reference testnet EVM chain ID required")
    for digest in ("genesis_sha256", "binary_sha256"):
        v = manifest.get(digest)
        require(isinstance(v, str) and HEX64.fullmatch(v) is not None,
                digest + " must contain a checked 64-hex hash")

    operators = manifest.get("operators")
    require(isinstance(operators, list) and len(operators) >= 4, ">=4 operator records required")
    if isinstance(operators, list):
        for attr in ("operator_id", "consensus_address", "fault_domain"):
            values = [x.get(attr) for x in operators if isinstance(x, dict)]
            require(len(values) == len(operators) and
                    all(isinstance(v, str) and v.strip() for v in values) and
                    len(set(v.lower() for v in values)) == len(values),
                    "operators must have unique, nonempty " + attr)
        for i, operator in enumerate(operators):
            if not isinstance(operator, dict):
                continue
            require(isinstance(operator.get("consensus_address"), str) and
                    HEX40.fullmatch(operator["consensus_address"]) is not None,
                    "operator %d has invalid CometBFT consensus address" % i)
            require(https_host(operator.get("independence_attestation_url")) is not None,
                    "operator %d needs an HTTPS identity/control attestation link" % i)
            require(operator.get("operator_controls_keys") is True,
                    "operator %d must claim direct key custody for review" % i)

    for field, count in (("comet_rpc", 4), ("evm_rpc", 2)):
        endpoints = manifest.get(field)
        require(isinstance(endpoints, list) and len(endpoints) >= count,
                "%s requires at least %d independent observation endpoints" % (field, count))
        if isinstance(endpoints, list):
            hosts = [https_host(url) for url in endpoints]
            require(all(h is not None for h in hosts), field + " must use valid HTTPS URLs without credentials")
            require(len(set(hosts)) == len(hosts), field + " observation hostnames must be unique")
    return errors

def check_genesis(genesis_file, manifest):
    source = Path(genesis_file)
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual.lower() != manifest["genesis_sha256"].lower():
        raise ValueError("genesis file SHA-256 does not match declared digest")
    doc = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("chain_id") != manifest["cosmos_chain_id"]:
        raise ValueError("candidate testnet genesis Cosmos chain ID mismatch")
    return actual

def hex_quantity(value, description):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value):
        raise ValueError(description + " must be hexadecimal RPC quantity")
    return int(value, 16)

def audit_evm_gateways(urls, expect_chain, rpc_factory=RPC):
    nodes = [rpc_factory(url) for url in urls]
    heights = []
    for node in nodes:
        seen = hex_quantity(node.call("eth_chainId"), "eth_chainId")
        if seen != expect_chain:
            raise ValueError("EVM gateway chain mismatch: expected %d, observed %d" % (expect_chain, seen))
        height = hex_quantity(node.call("eth_blockNumber"), "eth_blockNumber")
        if height < 2:
            raise ValueError("EVM gateway has insufficient block history")
        heights.append(height)
    common = min(heights) - 1
    if max(heights) - min(heights) > 10:
        raise ValueError("EVM gateways too far apart in height")
    hashes = []
    for node in nodes:
        block = node.call("eth_getBlockByNumber", [hex(common), False])
        value = block.get("hash") if isinstance(block, dict) else None
        if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{64}", value):
            raise ValueError("missing/invalid historical EVM block hash")
        hashes.append(value.lower())
    if len(set(hashes)) != 1:
        raise ValueError("EVM gateway block hashes disagree at common height")
    return {"chain_id": expect_chain, "common_block": common,
            "common_hash": hashes[0], "gateway_count": len(urls)}

def audit_network(manifest, consensus_probe=comet_audit,
                  validator_probe=validator_set, evm_probe=audit_evm_gateways):
    problems = validate_manifest(manifest)
    if problems:
        raise ValueError("; ".join(problems))
    comet = consensus_probe(manifest["comet_rpc"], expected=manifest["cosmos_chain_id"])
    observed = validator_probe(manifest["comet_rpc"][0], comet["blockHeight"])
    positive = {str(address).upper() for address, power in observed.items() if power > 0}
    declared = {v["consensus_address"].upper() for v in manifest["operators"]}
    if not declared.issubset(positive):
        raise ValueError("attested operator consensus address absent from live voting validator set")
    evm = evm_probe(manifest["evm_rpc"], manifest["evm_chain_id"])
    return {
        "result": "OBSERVATION_CHECKS_PASSED_NOT_FINAL_LAUNCH_APPROVAL",
        "cosmos_chain_id": manifest["cosmos_chain_id"],
        "cometbft": comet,
        "verified_operator_address_count": len(declared),
        "evm": evm,
        "limitations": [
            "operator independence/identity/cryptographic attestations require external verification",
            "binary hash must be reproduced and audited on each host",
            "genesis signature ceremony, key recovery and failure drills not verified by RPC",
            "wallet signing, actual native transfers, receipts and contract behavior still require tests",
            "does NOT authorize financial PRVI issuance, mainnet, sales or listings"
        ]
    }

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--genesis", type=Path, required=True)
    p.add_argument("--check-live", action="store_true",
                   help="explicitly opt into contacting only the reviewer's declared testnet RPC endpoints")
    args = p.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        problems = validate_manifest(manifest)
        if problems:
            raise ValueError("; ".join(problems))
        sha = check_genesis(args.genesis, manifest)
        if not args.check_live:
            result = {"ok": True, "type": "STATIC_MANIFEST_AND_GENESIS_ONLY",
                      "genesis_sha256": sha, "warning": "NO live proof and NO mainnet approval"}
        else:
            result = {"ok": True, "type": "READ_ONLY_PUBLIC_TESTNET_CHECK",
                      "genesis_sha256": sha, **audit_network(manifest)}
    except (ValueError, OSError, UnicodeError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
